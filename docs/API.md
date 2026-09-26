# API Reference: EVE Diagnostic Bookings

This document describes every endpoint of the service: what to send, what comes back, and which errors are possible. It also lists what was implemented for each requirement of the assignment.

**Every example in this document was produced by sending the request to the running API** (with the demo data from `python -m app.seed`). The only values that will differ on your machine are timestamps, tokens and the random `provider_ref`.

For setup instructions, the database design and the reasoning behind the design, see the [README](../README.md). The same endpoints can be tried interactively in Swagger UI at `http://localhost:8000/docs`.

## Contents

1. [What is implemented](#1-what-is-implemented)
2. [Conventions](#2-conventions)
3. [Endpoints](#3-endpoints)
   - [Health](#31-health) · [Auth](#32-authentication) · [Catalogue](#33-centres-and-tests) · [Bookings](#34-bookings) · [Payments](#35-payments) · [Webhook](#36-payment-webhook)
4. [Response objects](#4-response-objects)
5. [Error scenarios at a glance](#5-error-scenarios-at-a-glance)

---

## 1. What is implemented

### Required features

| # | Requirement | Implementation | Endpoints |
|---|---|---|---|
| 1 | Signup, login, JWT, request validation | bcrypt password hashing. JWT (HS256, 60-minute expiry). Emails are normalised to lower case and must be unique. Passwords need at least 8 characters, including a letter and a digit. Every request body is validated with Pydantic. | `POST /auth/signup/`, `POST /auth/login/`, `GET /auth/me/` |
| 2 | Centres and the tests they offer, with prices | A shared test catalogue. Each centre sets its own price per test (`centre_tests`), and can deactivate a test. Public read endpoints with filters and pagination; write endpoints are admin only. | `/centres/…`, `/tests/` |
| 3 | Booking with user, test, centre, time, amount and status | The amount is copied from the centre's price when the booking is made. The appointment time must be in the future and include a timezone. The same user cannot hold two live bookings for the same slot. Statuses are PENDING, CONFIRMED, FAILED and CANCELLED, and only the allowed transitions are possible. | `/bookings/…` |
| 4 | Mock payment: `POST /payments/`, SUCCESS or FAILED, booking updated | A mock provider returns SUCCESS or FAILED (random, or forced with `simulate`). The booking becomes CONFIRMED or FAILED. A failed payment can be retried. `simulate: "pending"` leaves the result to the webhook. | `POST /payments/` |
| 5 | Idempotent webhook: `POST /payments/webhook/` | The request is verified with an HMAC-SHA256 signature. Events are deduplicated by a unique `event_id`. The booking row is locked while the event is applied. A contradicting event that arrives later cannot corrupt the state. | `POST /payments/webhook/` |
| 6 | Edge cases | Invalid requests (`422`), repeated webhooks (`duplicate`), invalid booking IDs (`404`/`422`), failed payments (booking `FAILED`, retry allowed), unauthorised access (`401`/`403`/`404`). See [section 5](#5-error-scenarios-at-a-glance). | all |

### Extra safeguards

- **Idempotent payment retries.** `POST /payments/` accepts an `Idempotency-Key` header. Retrying with the same key returns the original payment instead of charging again.
- **Safe under concurrency.** Every change to a booking or its payments locks the booking row first. Parallel payments, retries and webhook deliveries are covered by tests.
- **Rules backed by the database.** Partial unique indexes guarantee one live booking per slot, one in-flight payment and one successful payment per booking.
- **Refunds are flagged.** Money that arrives for a cancelled booking, or a cancelled booking that was already paid, sets `refund_required: true` on the payment.
- **Other users' resources return 404.** Asking for another user's booking gives `404`, not `403`, so the API doesn't reveal which booking IDs exist.

### Optional bonus items

| Bonus | Status |
|---|---|
| Docker & docker-compose | ✅ `docker compose up` starts the API and Postgres, and runs the migrations |
| Swagger / OpenAPI | ✅ `/docs` and `/redoc`, with the error responses of every endpoint documented |
| Unit / integration tests | ✅ 117 tests against a real PostgreSQL, including concurrency tests |
| Structured logging | ✅ JSON log lines with `request_id`, status and duration, plus domain events (`booking.created`, `webhook.processed`, …) |
| Pagination | ✅ `page` / `page_size` on every list endpoint |
| Rate limiting | ✅ `POST /auth/login/` allows 5 requests per minute per IP |
| Retry handling for webhooks | ⚠️ Partial. A failed webhook rolls back completely, including the stored event, so the provider's retry is processed normally. There is no internal retry queue. |
| Redis caching | ❌ Not implemented (listed under future improvements) |
| Celery / background jobs | ❌ Not implemented (listed under future improvements) |

---

## 2. Conventions

**Base URL:** `http://localhost:8000`

**Authentication.**
- Get a token from `POST /auth/login/` and send it on every protected request:
  ```
  Authorization: Bearer <access_token>
  ```
- Tokens expire after 60 minutes (`expires_in: 3600`).
- A missing, malformed, expired or tampered token returns `401` with the header `WWW-Authenticate: Bearer`.

**Admin.** Endpoints marked *admin* need a user with `is_admin = true`. Signup can never create an admin; the seed script creates one: `admin@example.com` / `Admin@12345`.

**Trailing slash.** Every path ends with `/` (as in `POST /payments/`), except `/health`.

**Money.** Amounts are `NUMERIC(10,2)` in the database. The API returns them as **strings** (`"400.00"`) so no precision is lost. As input, both `"899.00"` and `899` are accepted.

**Date and time.**
- `appointment_at` must be ISO-8601 and **include a timezone**, e.g. `2026-12-05T09:30:00+05:30`.
- Responses always return times in UTC, so the example above comes back as `2026-12-05T04:00:00Z`.

**Pagination.** List endpoints take `page` (default 1) and `page_size` (default 20, maximum 100), and return:

```json
{ "items": [ ... ], "total": 42, "page": 1, "page_size": 20 }
```

**Errors.** Every error has the same shape:

```json
{ "detail": "Booking not found" }
```

Validation errors (`422`) return a list instead. Each entry has `loc` (where the error is), `msg` and `input`:

```json
{ "detail": [ { "type": "string_too_short", "loc": ["body", "password"], "msg": "String should have at least 8 characters", "input": "short" } ] }
```

| Status | Meaning |
|---|---|
| `200` / `201` | OK / created |
| `401` | Not authenticated: missing or invalid token, or a bad webhook signature |
| `403` | Authenticated, but not an admin |
| `404` | The resource does not exist, **or belongs to another user** |
| `409` | The request conflicts with the current state (duplicate, illegal status change, already paid, …) |
| `422` | The request failed validation |
| `429` | Rate limit exceeded |

**Request ID.** Every response carries an `X-Request-ID` header. If you send your own `X-Request-ID`, it is echoed back. The same ID appears in the server logs.

---

## 3. Endpoints

### 3.1 Health

#### `GET /health`

Checks that the API is running and can reach the database. No authentication.

```http
GET /health
```

Response `200 OK`

```json
{
  "status": "ok"
}
```

---

### 3.2 Authentication

#### `POST /auth/signup/`

Creates a patient account. No authentication.

| Field | Type | Rules |
|---|---|---|
| `email` | string | Valid email; stored in lower case; must be unique (case-insensitive) |
| `password` | string | 8 to 72 characters, at least one letter and one digit |
| `full_name` | string | 1 to 120 characters, not blank |

Any extra field is ignored. For example, `"is_admin": true` has no effect.

```http
POST /auth/signup/
Content-Type: application/json

{
  "email": "riya@example.com",
  "password": "Riya12345",
  "full_name": "Riya Sharma"
}
```

Response `201 Created`

```json
{
  "id": 2,
  "email": "riya@example.com",
  "full_name": "Riya Sharma",
  "is_admin": false,
  "created_at": "2026-09-26T16:13:34.065469Z"
}
```

**Email already registered (the check ignores case)**

```http
POST /auth/signup/
Content-Type: application/json

{
  "email": "RIYA@example.com",
  "password": "Riya12345",
  "full_name": "Riya"
}
```

Response `409 Conflict`

```json
{
  "detail": "An account with this email already exists"
}
```

**Validation errors (all problems are reported at once)**

```http
POST /auth/signup/
Content-Type: application/json

{
  "email": "riya@",
  "password": "short",
  "full_name": "Riya"
}
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": [
        "body",
        "email"
      ],
      "msg": "value is not a valid email address: There must be something after the @-sign.",
      "input": "riya@",
      "ctx": {
        "reason": "There must be something after the @-sign."
      }
    },
    {
      "type": "string_too_short",
      "loc": [
        "body",
        "password"
      ],
      "msg": "String should have at least 8 characters",
      "input": "short",
      "ctx": {
        "min_length": 8
      }
    }
  ]
}
```

#### `POST /auth/login/`

Returns a JWT. No authentication. **Rate limited to 5 requests per minute per IP.**

| Field | Type | Rules |
|---|---|---|
| `email` | string | Valid email |
| `password` | string | 1 to 72 characters |

```http
POST /auth/login/
Content-Type: application/json

{
  "email": "riya@example.com",
  "password": "Riya12345"
}
```

Response `200 OK`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwiaWF0IjoxNzkwNDM5MjE0LCJleHAiOjE3OTA0NDI4MTR9.r_EFfrPAmuUzEObLxrbOqqGZESNhC6PZcZqtrgXYqsA",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Wrong password (an unknown email gives exactly the same response, so the API doesn't reveal which emails are registered)**

```http
POST /auth/login/
Content-Type: application/json

{
  "email": "riya@example.com",
  "password": "Wrong1234"
}
```

Response `401 Unauthorized`

```json
{
  "detail": "Invalid email or password"
}
```

**6th attempt within a minute**

```http
POST /auth/login/
Content-Type: application/json

{
  "email": "x@example.com",
  "password": "Wrong1234"
}
```

Response `429 Too Many Requests`

```json
{
  "detail": "Rate limit exceeded: 5 per 1 minute"
}
```

#### `GET /auth/me/`

Returns the logged-in user. **Auth: user.**

```http
GET /auth/me/
Authorization: Bearer <access_token>
```

Response `200 OK`

```json
{
  "id": 2,
  "email": "riya@example.com",
  "full_name": "Riya Sharma",
  "is_admin": false,
  "created_at": "2026-09-26T16:13:34.065469Z"
}
```

**No token**

```http
GET /auth/me/
```

Response `401 Unauthorized`

```json
{
  "detail": "Not authenticated"
}
```

**Invalid or expired token**

```http
GET /auth/me/
Authorization: Bearer not-a-real-token
```

Response `401 Unauthorized`

```json
{
  "detail": "Invalid authentication token"
}
```

---

### 3.3 Centres and tests

Reading the catalogue is public. Changing it is **admin only**.

#### `GET /centres/`

Lists centres, with filters and pagination.

| Query param | Type | Description |
|---|---|---|
| `city` | string | Case-insensitive exact match |
| `test_id` | int | Only centres that currently offer this test |
| `page`, `page_size` | int | See [pagination](#2-conventions) |

```http
GET /centres/?city=mumbai&page=1&page_size=20
```

Response `200 OK`

```json
{
  "items": [
    {
      "id": 2,
      "name": "Metropolis Andheri",
      "city": "Mumbai",
      "address": "Veera Desai Road, Andheri West"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

**Invalid pagination**

```http
GET /centres/?page=0
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "greater_than_equal",
      "loc": [
        "query",
        "page"
      ],
      "msg": "Input should be greater than or equal to 1",
      "input": "0",
      "ctx": {
        "ge": 1
      }
    }
  ]
}
```

#### `GET /centres/{centre_id}/`

One centre, with the tests it currently offers and their prices. Deactivated tests are not shown.

```http
GET /centres/2/
```

Response `200 OK`

```json
{
  "id": 2,
  "name": "Metropolis Andheri",
  "city": "Mumbai",
  "address": "Veera Desai Road, Andheri West",
  "tests": [
    {
      "test_id": 1,
      "test_name": "Complete Blood Count",
      "description": "Haemoglobin, WBC, RBC and platelet counts",
      "price": "400.00",
      "is_active": true
    },
    {
      "test_id": 2,
      "test_name": "Lipid Profile",
      "description": "Total cholesterol, HDL, LDL and triglycerides",
      "price": "700.00",
      "is_active": true
    },
    {
      "test_id": 3,
      "test_name": "Thyroid Profile",
      "description": "T3, T4 and TSH",
      "price": "550.00",
      "is_active": true
    }
  ]
}
```

**Unknown centre**

```http
GET /centres/999/
```

Response `404 Not Found`

```json
{
  "detail": "Centre not found"
}
```

#### `POST /centres/`

Creates a centre. **Auth: admin.**

| Field | Type | Rules |
|---|---|---|
| `name` | string | up to 200 characters, not blank |
| `city` | string | up to 100 characters, not blank |
| `address` | string | up to 500 characters, not blank |

```http
POST /centres/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "Thyrocare Kothrud",
  "city": "Pune",
  "address": "Karve Road, Kothrud"
}
```

Response `201 Created`

```json
{
  "id": 4,
  "name": "Thyrocare Kothrud",
  "city": "Pune",
  "address": "Karve Road, Kothrud"
}
```

**Logged in as a normal user**

```http
POST /centres/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "X",
  "city": "Pune",
  "address": "Y"
}
```

Response `403 Forbidden`

```json
{
  "detail": "Admin access required"
}
```

#### `PATCH /centres/{centre_id}/`

Partial update: only the fields you send are changed. **Auth: admin.** Same field rules as `POST`. At least one field is required, and a field cannot be set to `null` or a blank string.

```http
PATCH /centres/4/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "address": "Paud Road, Kothrud"
}
```

Response `200 OK`

```json
{
  "id": 4,
  "name": "Thyrocare Kothrud",
  "city": "Pune",
  "address": "Paud Road, Kothrud"
}
```

**Empty body**

```http
PATCH /centres/4/
Authorization: Bearer <access_token>
Content-Type: application/json

{}
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": [
        "body"
      ],
      "msg": "Value error, provide at least one field to update",
      "input": {},
      "ctx": {
        "error": {}
      }
    }
  ]
}
```

#### `PUT /centres/{centre_id}/tests/{test_id}/`

Sets the price of a test at a centre. It creates the offering, or updates it if it already exists, so sending the same request twice gives the same result. **Auth: admin.**

| Field | Type | Rules |
|---|---|---|
| `price` | decimal | Greater than 0, at most 2 decimal places, at most 10 digits |
| `is_active` | bool | Default `true`. Set to `false` to stop offering the test; existing bookings are not affected. |

Errors: `404` if the centre or test doesn't exist; `401`/`403` if not an admin.

```http
PUT /centres/4/tests/5/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "price": "899.00"
}
```

Response `200 OK`

```json
{
  "test_id": 5,
  "test_name": "Vitamin D (25-OH)",
  "description": "Vitamin D level",
  "price": "899.00",
  "is_active": true
}
```

**Invalid price**

```http
PUT /centres/4/tests/5/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "price": "-5"
}
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "greater_than",
      "loc": [
        "body",
        "price"
      ],
      "msg": "Input should be greater than 0",
      "input": "-5",
      "ctx": {
        "gt": 0
      }
    }
  ]
}
```

#### `GET /tests/`

The test catalogue, sorted by name and paginated. No authentication.

```http
GET /tests/?page_size=2
```

Response `200 OK`

```json
{
  "items": [
    {
      "id": 1,
      "name": "Complete Blood Count",
      "description": "Haemoglobin, WBC, RBC and platelet counts"
    },
    {
      "id": 4,
      "name": "HbA1c",
      "description": "Average blood sugar over three months"
    }
  ],
  "total": 4,
  "page": 1,
  "page_size": 2
}
```

#### `POST /tests/`

Adds a test to the catalogue. **Auth: admin.** Test names must be unique. After creating a test, give it a price at a centre with `PUT /centres/{id}/tests/{test_id}/`.

| Field | Type | Rules |
|---|---|---|
| `name` | string | up to 200 characters, not blank, unique |
| `description` | string | optional, up to 2000 characters |

```http
POST /tests/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "Vitamin D (25-OH)",
  "description": "Vitamin D level"
}
```

Response `201 Created`

```json
{
  "id": 5,
  "name": "Vitamin D (25-OH)",
  "description": "Vitamin D level"
}
```

**Name already exists**

```http
POST /tests/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "Lipid Profile"
}
```

Response `409 Conflict`

```json
{
  "detail": "A test with this name already exists"
}
```

---

### 3.4 Bookings

All booking endpoints need **auth: user**. A user only ever sees their own bookings.

#### `POST /bookings/`

Books a test at a centre. The booking starts as `PENDING`, and `amount` is copied from the centre's current price.

| Field | Type | Rules |
|---|---|---|
| `centre_id` | int | Required |
| `test_id` | int | Required. The centre must offer this test and it must be active. |
| `appointment_at` | datetime | Required. Must include a timezone and be in the future. |

```http
POST /bookings/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "centre_id": 2,
  "test_id": 1,
  "appointment_at": "2026-12-05T09:30:00+05:30"
}
```

Response `201 Created`

```json
{
  "id": 1,
  "user_id": 2,
  "centre_id": 2,
  "centre_name": "Metropolis Andheri",
  "test_id": 1,
  "test_name": "Complete Blood Count",
  "appointment_at": "2026-12-05T09:30:00+05:30",
  "amount": "400.00",
  "status": "PENDING",
  "created_at": "2026-09-26T16:13:34.317426Z",
  "updated_at": "2026-09-26T16:13:34.317426Z",
  "payments": []
}
```

**Same user, centre, test and time while the first booking is still PENDING or CONFIRMED**

```http
POST /bookings/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "centre_id": 2,
  "test_id": 1,
  "appointment_at": "2026-12-05T09:30:00+05:30"
}
```

Response `409 Conflict`

```json
{
  "detail": "You already have an active booking for this test at this centre and time"
}
```

**The centre doesn't offer this test**

```http
POST /bookings/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "centre_id": 2,
  "test_id": 4,
  "appointment_at": "2026-12-05T09:30:00+05:30"
}
```

Response `404 Not Found`

```json
{
  "detail": "This test is not offered at this centre"
}
```

**Appointment time in the past**

```http
POST /bookings/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "centre_id": 2,
  "test_id": 1,
  "appointment_at": "2024-01-01T10:00:00+05:30"
}
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": [
        "body",
        "appointment_at"
      ],
      "msg": "Value error, must be in the future",
      "input": "2024-01-01T10:00:00+05:30",
      "ctx": {
        "error": {}
      }
    }
  ]
}
```

**No token**

```http
POST /bookings/
Content-Type: application/json

{
  "centre_id": 2,
  "test_id": 1,
  "appointment_at": "2026-12-05T09:30:00+05:30"
}
```

Response `401 Unauthorized`

```json
{
  "detail": "Not authenticated"
}
```

#### `GET /bookings/`

Lists your own bookings, newest first.

| Query param | Type | Description |
|---|---|---|
| `status` | `PENDING` \| `CONFIRMED` \| `FAILED` \| `CANCELLED` | Optional filter |
| `page`, `page_size` | int | See [pagination](#2-conventions) |

```http
GET /bookings/?status=CONFIRMED&page=1&page_size=20
Authorization: Bearer <access_token>
```

Response `200 OK`

```json
{
  "items": [
    {
      "id": 4,
      "user_id": 2,
      "centre_id": 3,
      "centre_name": "Dr Lal PathLabs Saket",
      "test_id": 3,
      "test_name": "Thyroid Profile",
      "appointment_at": "2026-12-07T02:30:00Z",
      "amount": "480.00",
      "status": "CONFIRMED",
      "created_at": "2026-09-26T16:13:34.397649Z",
      "updated_at": "2026-09-26T16:13:34.604034Z"
    },
    {
      "id": 3,
      "user_id": 2,
      "centre_id": 1,
      "centre_name": "Apollo Diagnostics Koramangala",
      "test_id": 2,
      "test_name": "Lipid Profile",
      "appointment_at": "2026-12-06T04:30:00Z",
      "amount": "650.00",
      "status": "CONFIRMED",
      "created_at": "2026-09-26T16:13:34.378606Z",
      "updated_at": "2026-09-26T16:13:34.524156Z"
    },
    {
      "id": 1,
      "user_id": 2,
      "centre_id": 2,
      "centre_name": "Metropolis Andheri",
      "test_id": 1,
      "test_name": "Complete Blood Count",
      "appointment_at": "2026-12-05T04:00:00Z",
      "amount": "400.00",
      "status": "CONFIRMED",
      "created_at": "2026-09-26T16:13:34.317426Z",
      "updated_at": "2026-09-26T16:13:34.436191Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20
}
```

#### `GET /bookings/{booking_id}/`

One booking, with all its payment attempts in order. This example is a booking whose first payment failed and whose retry succeeded:

```http
GET /bookings/3/
Authorization: Bearer <access_token>
```

Response `200 OK`

```json
{
  "id": 3,
  "user_id": 2,
  "centre_id": 1,
  "centre_name": "Apollo Diagnostics Koramangala",
  "test_id": 2,
  "test_name": "Lipid Profile",
  "appointment_at": "2026-12-06T04:30:00Z",
  "amount": "650.00",
  "status": "CONFIRMED",
  "created_at": "2026-09-26T16:13:34.378606Z",
  "updated_at": "2026-09-26T16:13:34.524156Z",
  "payments": [
    {
      "id": 2,
      "amount": "650.00",
      "status": "FAILED",
      "provider_ref": "sim_25733fbb8bc64d3dbddcf65f523157f2",
      "refund_required": false,
      "created_at": "2026-09-26T16:13:34.506854Z"
    },
    {
      "id": 3,
      "amount": "650.00",
      "status": "SUCCESS",
      "provider_ref": "sim_6f1027a94e524cc798938d64cbc852ea",
      "refund_required": false,
      "created_at": "2026-09-26T16:13:34.524156Z"
    }
  ]
}
```

**Another user's booking returns 404, not 403**

```http
GET /bookings/3/
Authorization: Bearer <access_token>
```

Response `404 Not Found`

```json
{
  "detail": "Booking not found"
}
```

**Booking ID that isn't a number**

```http
GET /bookings/abc/
Authorization: Bearer <access_token>
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": [
        "path",
        "booking_id"
      ],
      "msg": "Input should be a valid integer, unable to parse string as an integer",
      "input": "abc"
    }
  ]
}
```

#### `POST /bookings/{booking_id}/cancel/`

Cancels a booking in `PENDING`, `FAILED` or `CONFIRMED` status.
- If the booking was already paid, its successful payment gets `refund_required: true`.
- Cancelling an already-cancelled booking returns `200` and changes nothing.
- Cancelling after the appointment time returns `409`.

**Cancelling a confirmed (paid) booking: the payment is flagged for refund**

```http
POST /bookings/1/cancel/
Authorization: Bearer <access_token>
```

Response `200 OK`

```json
{
  "id": 1,
  "user_id": 2,
  "centre_id": 2,
  "centre_name": "Metropolis Andheri",
  "test_id": 1,
  "test_name": "Complete Blood Count",
  "appointment_at": "2026-12-05T04:00:00Z",
  "amount": "400.00",
  "status": "CANCELLED",
  "created_at": "2026-09-26T16:13:34.317426Z",
  "updated_at": "2026-09-26T16:13:34.814030Z",
  "payments": [
    {
      "id": 1,
      "amount": "400.00",
      "status": "SUCCESS",
      "provider_ref": "sim_bc039d96d5674ff39ac563b26a95b906",
      "refund_required": true,
      "created_at": "2026-09-26T16:13:34.436191Z"
    }
  ]
}
```

**Cancelling it again**

```http
POST /bookings/1/cancel/
Authorization: Bearer <access_token>
```

Response `200 OK`

```json
{
  "id": 1,
  "user_id": 2,
  "centre_id": 2,
  "centre_name": "Metropolis Andheri",
  "test_id": 1,
  "test_name": "Complete Blood Count",
  "appointment_at": "2026-12-05T04:00:00Z",
  "amount": "400.00",
  "status": "CANCELLED",
  "created_at": "2026-09-26T16:13:34.317426Z",
  "updated_at": "2026-09-26T16:13:34.814030Z",
  "payments": [
    {
      "id": 1,
      "amount": "400.00",
      "status": "SUCCESS",
      "provider_ref": "sim_bc039d96d5674ff39ac563b26a95b906",
      "refund_required": true,
      "created_at": "2026-09-26T16:13:34.436191Z"
    }
  ]
}
```

---

### 3.5 Payments

#### `POST /payments/`

Pays for one of your bookings through the mock payment provider. **Auth: user** (you must own the booking).

| Field | Type | Rules |
|---|---|---|
| `booking_id` | int | Required |
| `simulate` | `"success"` \| `"failed"` \| `"pending"` | Optional. Forces the mock provider's result. If omitted, the result is random: SUCCESS with probability `PAYMENT_SUCCESS_RATE` (default 0.8). `"pending"` leaves the payment in progress until the [webhook](#36-payment-webhook) reports the result. |

| Header | Description |
|---|---|
| `Idempotency-Key` | Optional, at most 128 characters. Retrying with the same key returns the original payment (`200`) instead of charging again. |

What happens to the booking:

| Payment result | Booking becomes |
|---|---|
| `SUCCESS` | `CONFIRMED` |
| `FAILED` | `FAILED` (paying again is allowed) |
| `PENDING` | stays as it was until the webhook arrives |

A booking can be paid only if it is `PENDING` or `FAILED`, its appointment time hasn't passed, and no other payment for it is in progress.

**Successful payment**

```http
POST /payments/
Authorization: Bearer <access_token>
Idempotency-Key: 7d2f-0001
Content-Type: application/json

{
  "booking_id": 1,
  "simulate": "success"
}
```

Response `201 Created`

```json
{
  "id": 1,
  "booking_id": 1,
  "amount": "400.00",
  "status": "SUCCESS",
  "provider_ref": "sim_bc039d96d5674ff39ac563b26a95b906",
  "refund_required": false,
  "booking_status": "CONFIRMED",
  "created_at": "2026-09-26T16:13:34.436191Z"
}
```

**Same request again with the same Idempotency-Key: the original payment is returned and nothing is charged**

```http
POST /payments/
Authorization: Bearer <access_token>
Idempotency-Key: 7d2f-0001
Content-Type: application/json

{
  "booking_id": 1,
  "simulate": "success"
}
```

Response `200 OK`

```json
{
  "id": 1,
  "booking_id": 1,
  "amount": "400.00",
  "status": "SUCCESS",
  "provider_ref": "sim_bc039d96d5674ff39ac563b26a95b906",
  "refund_required": false,
  "booking_status": "CONFIRMED",
  "created_at": "2026-09-26T16:13:34.436191Z"
}
```

**Paying a booking that is already confirmed**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 1,
  "simulate": "success"
}
```

Response `409 Conflict`

```json
{
  "detail": "Booking is CONFIRMED; it cannot be paid"
}
```

**Reusing an Idempotency-Key for a different booking**

```http
POST /payments/
Authorization: Bearer <access_token>
Idempotency-Key: 7d2f-0001
Content-Type: application/json

{
  "booking_id": 3,
  "simulate": "success"
}
```

Response `409 Conflict`

```json
{
  "detail": "Idempotency-Key was already used for a different request"
}
```

**Failed payment**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 3,
  "simulate": "failed"
}
```

Response `201 Created`

```json
{
  "id": 2,
  "booking_id": 3,
  "amount": "650.00",
  "status": "FAILED",
  "provider_ref": "sim_25733fbb8bc64d3dbddcf65f523157f2",
  "refund_required": false,
  "booking_status": "FAILED",
  "created_at": "2026-09-26T16:13:34.506854Z"
}
```

**Retrying after a failure**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 3,
  "simulate": "success"
}
```

Response `201 Created`

```json
{
  "id": 3,
  "booking_id": 3,
  "amount": "650.00",
  "status": "SUCCESS",
  "provider_ref": "sim_6f1027a94e524cc798938d64cbc852ea",
  "refund_required": false,
  "booking_status": "CONFIRMED",
  "created_at": "2026-09-26T16:13:34.524156Z"
}
```

**Payment in progress: the result will arrive by webhook**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 4,
  "simulate": "pending"
}
```

Response `201 Created`

```json
{
  "id": 4,
  "booking_id": 4,
  "amount": "480.00",
  "status": "PENDING",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "refund_required": false,
  "booking_status": "PENDING",
  "created_at": "2026-09-26T16:13:34.541992Z"
}
```

**A second payment while one is still in progress**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 4,
  "simulate": "success"
}
```

Response `409 Conflict`

```json
{
  "detail": "A payment for this booking is already in progress"
}
```

**Paying for a cancelled booking**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 1,
  "simulate": "success"
}
```

Response `409 Conflict`

```json
{
  "detail": "Booking is CANCELLED; it cannot be paid"
}
```

**Booking doesn't exist**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 999
}
```

Response `404 Not Found`

```json
{
  "detail": "Booking not found"
}
```

**Someone else's booking**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 4
}
```

Response `404 Not Found`

```json
{
  "detail": "Booking not found"
}
```

**Invalid `simulate` value**

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": 4,
  "simulate": "maybe"
}
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": [
        "body",
        "simulate"
      ],
      "msg": "Input should be 'success', 'failed' or 'pending'",
      "input": "maybe",
      "ctx": {
        "expected": "'success', 'failed' or 'pending'"
      }
    }
  ]
}
```

---

### 3.6 Payment webhook

#### `POST /payments/webhook/`

Called by the payment provider (simulated) to report the final result of a payment. It uses **no JWT**. Instead, the provider signs the raw request body:

```
X-Signature: hex( HMAC-SHA256( WEBHOOK_SECRET, raw_request_body ) )
```

| Field | Type | Rules |
|---|---|---|
| `event_id` | string | 1 to 128 characters. Unique per event, used for deduplication. |
| `provider_ref` | string | The `provider_ref` returned by `POST /payments/` |
| `status` | `"SUCCESS"` \| `"FAILED"` | The final result of the payment |

**Processing** (all in one database transaction):
1. Check the signature. If it's wrong, return `401` and do nothing else.
2. Insert the `event_id` with `ON CONFLICT DO NOTHING`. If it already exists, return `200 duplicate` and change nothing.
3. Lock the booking row, then apply the status to the payment and the booking.
4. Commit. If anything fails, everything is rolled back, including the stored event, so the provider's retry is processed normally.

The `result` field in the response:

| `result` | Meaning |
|---|---|
| `applied` | The payment status changed, and the booking was updated |
| `duplicate` | This `event_id` was already processed. Nothing changed. |
| `already_applied` | A new event, but the payment already has this status (e.g. the provider also reports a payment that was settled immediately). Nothing changed. |
| `ignored_conflict` | The payment already has the *other* final status (e.g. FAILED arriving after SUCCESS). Ignored and logged for reconciliation. |

A helper script sends signed webhooks for you:

```bash
docker compose exec api python -m scripts.send_webhook <provider_ref> SUCCESS --event-id evt_1001
```

**Event applied: the in-progress payment succeeds and the booking is confirmed**

```http
POST /payments/webhook/
X-Signature: d41ca51013e388ae9f74aa6ee01e812ff2d5210d56c528875c0ec9da5bd5017d
Content-Type: application/json

{
  "event_id": "evt_1001",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "status": "SUCCESS"
}
```

Response `200 OK`

```json
{
  "event_id": "evt_1001",
  "result": "applied",
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED"
}
```

**The same event delivered again**

```http
POST /payments/webhook/
X-Signature: d41ca51013e388ae9f74aa6ee01e812ff2d5210d56c528875c0ec9da5bd5017d
Content-Type: application/json

{
  "event_id": "evt_1001",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "status": "SUCCESS"
}
```

Response `200 OK`

```json
{
  "event_id": "evt_1001",
  "result": "duplicate",
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED"
}
```

**A different event with the same status**

```http
POST /payments/webhook/
X-Signature: 98af2ca3c10e77048de5eb588ee0f3187a32c94673892e5a9367e2aa458ce4c5
Content-Type: application/json

{
  "event_id": "evt_1002",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "status": "SUCCESS"
}
```

Response `200 OK`

```json
{
  "event_id": "evt_1002",
  "result": "already_applied",
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED"
}
```

**A late, contradicting event: the booking stays CONFIRMED**

```http
POST /payments/webhook/
X-Signature: 05903c0c540107478c6ca18d87523d84cb2afa6be091d8fc9dcb9906ffe348e6
Content-Type: application/json

{
  "event_id": "evt_1003",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "status": "FAILED"
}
```

Response `200 OK`

```json
{
  "event_id": "evt_1003",
  "result": "ignored_conflict",
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED"
}
```

**SUCCESS for a booking the user cancelled while payment was in progress: the booking stays CANCELLED and the payment is flagged `refund_required`**

```http
POST /payments/webhook/
X-Signature: d2e2df5776c1674c7ea7afeff6e39c10e6494bfd07bdd781495d6ff49afb8f69
Content-Type: application/json

{
  "event_id": "evt_1006",
  "provider_ref": "sim_51be6d64b156497bab127882b6599f4d",
  "status": "SUCCESS"
}
```

Response `200 OK`

```json
{
  "event_id": "evt_1006",
  "result": "applied",
  "payment_status": "SUCCESS",
  "booking_status": "CANCELLED"
}
```

**Wrong signature**

```http
POST /payments/webhook/
X-Signature: deadbeef
Content-Type: application/json

{
  "event_id": "evt_1001",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "status": "SUCCESS"
}
```

Response `401 Unauthorized`

```json
{
  "detail": "Invalid webhook signature"
}
```

**Unknown `provider_ref` (the event is not stored)**

```http
POST /payments/webhook/
X-Signature: 8724c0ad81fa0d9ec4ce2cf08a42058f1e08d1684acb0cd5e8f6e678d890532f
Content-Type: application/json

{
  "event_id": "evt_1004",
  "provider_ref": "sim_does_not_exist",
  "status": "SUCCESS"
}
```

Response `404 Not Found`

```json
{
  "detail": "Unknown payment reference"
}
```

**Invalid body (checked after the signature)**

```http
POST /payments/webhook/
X-Signature: 5811dd4f97bf79afa398f015e2896aa49bca15bc8d5147c6d911f16f18a8d4e4
Content-Type: application/json

{
  "event_id": "evt_1005",
  "provider_ref": "sim_95d270f54ece465eb336d8f48e7abaf0",
  "status": "REFUNDED"
}
```

Response `422 Unprocessable Entity`

```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": [
        "body",
        "status"
      ],
      "msg": "Input should be 'SUCCESS' or 'FAILED'",
      "input": "REFUNDED",
      "ctx": {
        "expected": "'SUCCESS' or 'FAILED'"
      }
    }
  ]
}
```

---

## 4. Response objects

**User**

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `email` | string | lower case |
| `full_name` | string | |
| `is_admin` | bool | |
| `created_at` | datetime (UTC) | |

**Token:** `access_token` (string), `token_type` (`"bearer"`), `expires_in` (seconds).

**Centre:** `id`, `name`, `city`, `address`. The centre detail adds `tests`: a list of **Offering** objects.

**Offering**

| Field | Type |
|---|---|
| `test_id` | int |
| `test_name` | string |
| `description` | string or null |
| `price` | decimal string |
| `is_active` | bool |

**Diagnostic test:** `id`, `name`, `description`.

**Booking**

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `user_id` | int | the owner |
| `centre_id`, `centre_name` | int, string | |
| `test_id`, `test_name` | int, string | |
| `appointment_at` | datetime (UTC) | |
| `amount` | decimal string | price copied at booking time |
| `status` | `PENDING` \| `CONFIRMED` \| `FAILED` \| `CANCELLED` | |
| `created_at`, `updated_at` | datetime (UTC) | |
| `payments` | list of payment summaries | only on create, detail and cancel responses |

**Payment**

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `booking_id` | int | only on `POST /payments/` responses |
| `amount` | decimal string | |
| `status` | `PENDING` \| `SUCCESS` \| `FAILED` | |
| `provider_ref` | string | the reference webhooks use to identify this payment |
| `refund_required` | bool | money was taken but the booking can't use it |
| `booking_status` | booking status | only on `POST /payments/` responses |
| `created_at` | datetime (UTC) | |

**Webhook result:** `event_id`, `result` (see [3.6](#36-payment-webhook)), `payment_status`, `booking_status`.

---

## 5. Error scenarios at a glance

| Scenario | Endpoint | Status | `detail` |
|---|---|---|---|
| Email already registered | `POST /auth/signup/` | `409` | An account with this email already exists |
| Invalid signup data | `POST /auth/signup/` | `422` | value is not a valid email address: There must be something after the @-sign. |
| Wrong email or password | `POST /auth/login/` | `401` | Invalid email or password |
| Too many login attempts | `POST /auth/login/` | `429` | Rate limit exceeded: 5 per 1 minute |
| No token | `GET /auth/me/` | `401` | Not authenticated |
| Invalid or expired token | `GET /auth/me/` | `401` | Invalid authentication token |
| Non-admin changes the catalogue | `POST /centres/` | `403` | Admin access required |
| Unknown centre | `GET /centres/{id}/` | `404` | Centre not found |
| Empty PATCH body | `PATCH /centres/{id}/` | `422` | Value error, provide at least one field to update |
| Duplicate test name | `POST /tests/` | `409` | A test with this name already exists |
| Price ≤ 0 | `PUT /centres/{id}/tests/{id}/` | `422` | Input should be greater than 0 |
| Test not offered at the centre | `POST /bookings/` | `404` | This test is not offered at this centre |
| Duplicate live booking for the same slot | `POST /bookings/` | `409` | You already have an active booking for this test at this centre and time |
| Appointment in the past | `POST /bookings/` | `422` | Value error, must be in the future |
| Another user's booking | `GET /bookings/{id}/` | `404` | Booking not found |
| Booking ID that isn't a number | `GET /bookings/abc/` | `422` | Input should be a valid integer, unable to parse string as an integer |
| Paying a confirmed booking | `POST /payments/` | `409` | Booking is CONFIRMED; it cannot be paid |
| Paying a cancelled booking | `POST /payments/` | `409` | Booking is CANCELLED; it cannot be paid |
| Second payment while one is in progress | `POST /payments/` | `409` | A payment for this booking is already in progress |
| Idempotency-Key reused for another booking | `POST /payments/` | `409` | Idempotency-Key was already used for a different request |
| Paying a booking that doesn't exist | `POST /payments/` | `404` | Booking not found |
| Paying another user's booking | `POST /payments/` | `404` | Booking not found |
| Webhook with a bad signature | `POST /payments/webhook/` | `401` | Invalid webhook signature |
| Webhook for an unknown payment | `POST /payments/webhook/` | `404` | Unknown payment reference |
| Webhook with an invalid status | `POST /payments/webhook/` | `422` | Input should be 'SUCCESS' or 'FAILED' |
