# FoodVault Backend

This is a monolithic FastAPI backend for the Strategic Food Vault application.
It is built around a single relational PostgreSQL database and local file storage for product images.

## Architecture

- `main.py` — API routes, auth dependencies, dashboard, cart, checkout, reserve, and admin endpoints.
- `models.py` — SQLAlchemy ORM tables for `user_profiles`, `products`, `product_images`, `inventory`, `carts`, `cart_items`, `orders`, `order_items`, `payments`, `reserve_vaults`, `reserve_items`, `delivery_schedules`, `notifications`, and `admin_users`.
- `services.py` — business logic for product management, cart workflows, checkout, reserve vault creation, inventory updates, analytics, and email notification delivery.
- `auth.py` — Supabase JWT validation plus local user/profile mapping and admin validation.
- `database.py` — DB engine configuration, session dependency, and schema initialization.

## Required environment variables

- `DATABASE_URL` or `SUPABASE_DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_AUD=authenticated`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `EMAIL_FROM`
- `BACKEND_URL`

## Running locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

## Local file uploads

Product images are stored under:

- `/backend/uploads/products/`

They are served at runtime from:

- `/uploads/products/{filename}`

## API routes and frontend integration

### Authentication

- `GET /api/auth/verify` — verify Supabase JWT and map to local user profile.
- `GET /api/user/profile` — fetch authenticated user profile.
- `PUT /api/user/profile` — update user details.

### Product catalog

- `GET /api/products` — product listing page.
- `GET /api/products/{product_id}` — product detail page.

### Cart and checkout

- `GET /api/cart` — fetch current cart.
- `POST /api/cart/items` — add item to cart.
- `PUT /api/cart/items/{item_id}` — update cart quantity.
- `DELETE /api/cart/items/{item_id}` — remove cart item.
- `POST /api/checkout` — complete purchase and update inventory.

### Reserve vault

- `POST /api/reserves` — lock prices by paying a deposit and create a reserve vault.
- `GET /api/reserves` — list active reserve vaults.
- `GET /api/dashboard` — dashboard data with active reserves, next deliveries, health score, and analytics.

### Admin

- `GET /api/admin/products` — list all products.
- `POST /api/admin/products` — create a product and upload up to 4 images.
- `PUT /api/admin/products/{product_id}` — update product, pricing, inventory, lock duration, delivery options.
- `DELETE /api/admin/products/{product_id}` — delete a product.
- `GET /api/admin/analytics` — admin dashboard analytics and inventory tracking.

### Notifications

- `GET /api/notifications` — user notifications.
- `POST /api/notifications/{notification_id}/read` — mark notifications as read.

## Frontend mapping

- Product listing: `/api/products`
- Product detail: `/api/products/{id}`
- Cart page: `/api/cart`
- Checkout page: `/api/checkout`
- Reserve planner: `/api/reserves`
- User dashboard: `/api/dashboard`
- Orders page: `/api/orders`
- Admin dashboard: `/api/admin/analytics`
- Admin product management: `/api/admin/products`

## Notes

- Google OAuth login is handled by Supabase client in the frontend.
- The frontend should send `Authorization: Bearer <supabase-access-token>` with all protected requests.
- Every checkout or reserve action updates inventory in real time and creates order/reserve records.
- Confirmation emails are sent using SMTP after order or reserve creation.
