import asyncio
import logging
import os
import re
import smtplib
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from fastapi import UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import (
    AdminUser,
    Cart,
    CartItem,
    DeliverySchedule,
    Inventory,
    Notification,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductImage,
    ReserveItem,
    ReservePosition,
    ReserveVault,
    UserProfile,
)
from backend.models_stripe import PaymentTransaction

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE_UPLOAD_FORMAT = "png"
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR.parent / "uploads" / "products"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def to_serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def model_to_dict(instance: Any, include_relationships: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for column in instance.__table__.columns:
        if column.name == "metadata" and hasattr(instance, "metadata_json"):
            data[column.name] = to_serializable(getattr(instance, "metadata_json"))
        else:
            data[column.name] = to_serializable(getattr(instance, column.key))

    if include_relationships:
        if hasattr(instance, "images"):
            data["images"] = [model_to_dict(image) for image in instance.images]
        if hasattr(instance, "inventory") and instance.inventory:
            data["inventory"] = model_to_dict(instance.inventory)
        if hasattr(instance, "items"):
            data["items"] = [model_to_dict(item, include_relationships=True) for item in instance.items]
        if hasattr(instance, "payments"):
            data["payments"] = [model_to_dict(payment) for payment in instance.payments]
        # Only include paid/active reserve_items
        if hasattr(instance, "reserve_items"):
            data["reserve_items"] = [
                model_to_dict(item, include_relationships=True)
                for item in instance.reserve_items
                if getattr(item, "status", None) in ("active_lock", "fully_owned", "partially_funded", "partially_delivered", "locked", "active")
            ]
        # Only include paid/active reserve_positions
        if hasattr(instance, "reserve_positions"):
            data["reserve_positions"] = [
                model_to_dict(pos, include_relationships=True)
                for pos in instance.reserve_positions
                if getattr(pos, "status", None) in ("active_lock", "fully_owned", "partially_funded", "partially_delivered", "locked", "active")
            ]
        if hasattr(instance, "schedules"):
            data["schedules"] = [model_to_dict(schedule) for schedule in instance.schedules]
        if hasattr(instance, "notifications"):
            data["notifications"] = [model_to_dict(note) for note in instance.notifications]
        if isinstance(instance, UserProfile):
            data["orders"] = [model_to_dict(order) for order in instance.orders]
            data["reserve_vaults"] = [model_to_dict(vault) for vault in instance.reserve_vaults if getattr(vault, "status", None) == "active"]
        if isinstance(instance, Order) and instance.user:
            data["user"] = model_to_dict(instance.user)
        if isinstance(instance, OrderItem) and instance.product:
            data["product"] = serialize_product(instance.product)
        if isinstance(instance, ReserveItem) and instance.product:
            data["product"] = serialize_product(instance.product)
    return data


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "product"


def get_product_image_urls(product: Product) -> List[str]:
    urls: List[str] = []
    for image in getattr(product, "images", []) or []:
        if isinstance(image, str):
            urls.append(image)
        elif hasattr(image, "url") and image.url:
            urls.append(image.url)
        elif isinstance(image, dict) and image.get("url"):
            urls.append(image["url"])

    if product.image and product.image not in urls:
        urls.insert(0, product.image)

    return urls


def serialize_product(product: Product) -> Dict[str, Any]:
    metadata = product.metadata_json or {}
    image_urls = get_product_image_urls(product)
    default_image = image_urls[0] if image_urls else "/assets/images/no_image.png"
    # Always use the first valid uploaded image as the main image if available
    main_image = image_urls[0] if image_urls else default_image
    category = product.category or metadata.get("category") or "Emergency Kits"
    locked_price = product.locked_price if product.locked_price is not None else product.reserve_lock_price

    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "price": to_serializable(product.price or Decimal("0")),
        "slug": product.slug or metadata.get("slug") or slugify(product.name),
        "category": category,
        "image": main_image,
        "images": image_urls or [default_image],
        "stock_quantity": product.stock_quantity if product.stock_quantity is not None else (getattr(product.inventory, "quantity", 0) if product.inventory else 0),
        "inflation_savings": to_serializable(product.inflation_savings or Decimal("0")),
        "storage_type": product.storage_type or metadata.get("storage_type") or "pantry",
        "reserve_lock_price": to_serializable(product.reserve_lock_price or product.price),
        "locked_price": to_serializable(locked_price or product.price),
        "lock_duration_days": product.lock_duration_days,
        "feeds_people": product.feeds_people or metadata.get("feeds_people") or 4,
        "reserve_days": product.reserve_days or metadata.get("reserve_days") or product.lock_duration_days or 30,
        "rating": to_serializable(product.rating if product.rating is not None else 4.7),
        "delivery_options": product.delivery_options,
        "is_active": product.is_active,
        "created_at": to_serializable(product.created_at),
        "updated_at": to_serializable(product.updated_at),
    }


def create_or_update_user_profile(db: Session, claims: dict) -> UserProfile:
    supabase_id = claims.get("sub")
    email = claims.get("email")
    name = claims.get("name") or claims.get("user_metadata", {}).get("full_name") or ""
    avatar_url = claims.get("picture") or claims.get("user_metadata", {}).get("avatar_url")
    role = claims.get("role") or claims.get("user_metadata", {}).get("role") or "customer"
    auth_provider = claims.get("provider", "supabase")
    metadata = dict(claims.get("metadata_json") or claims.get("metadata") or {})

    user = db.query(UserProfile).filter(UserProfile.supabase_user_id == supabase_id).one_or_none()
    if not user:
        # New user - create user profile with all required fields
        user = UserProfile(
            supabase_user_id=supabase_id,
            email=email,
            name=name,
            avatar_url=avatar_url,
            role=role,
            auth_provider=auth_provider,
            last_login=datetime.utcnow(),
            metadata_json={"source": "supabase", **metadata},
        )
        db.add(user)
        print(f"[auth] Created new user: {email} via {auth_provider} - services.py:157", flush=True)
    else:
        # Existing user - update fields (don't override existing data unless provided)
        user.email = email or user.email
        user.name = name or user.name
        user.avatar_url = avatar_url or user.avatar_url
        user.role = role or user.role
        user.auth_provider = auth_provider
        user.last_login = datetime.utcnow()
        existing_metadata = dict(user.metadata_json or {})
        existing_metadata.update(metadata)
        user.metadata_json = existing_metadata
        print(f"[auth] Updated existing user: {email}  last_login={user.last_login} - services.py:169", flush=True)
    
    db.commit()
    db.refresh(user)
    return user


def get_or_create_active_cart(db: Session, user: UserProfile) -> Cart:
    cart = db.query(Cart).filter(Cart.user_id == user.id, Cart.status == "active").one_or_none()
    if cart:
        return cart
    cart = Cart(user_id=user.id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def get_products(db: Session, active_only: bool = True) -> List[Product]:
    query = db.query(Product)
    if active_only:
        query = query.filter(Product.is_active.is_(True))
    return query.order_by(Product.name).all()


def get_product(db: Session, product_id: int) -> Optional[Product]:
    return db.query(Product).filter(Product.id == product_id, Product.is_active.is_(True)).one_or_none()


def save_product_image(file: UploadFile, product_id: int, is_primary: bool = False, sort_order: int = 0) -> ProductImage:
    if not file.filename:
        raise ValueError("Uploaded image is missing a filename")

    normalized_content_type = (file.content_type or "").lower()
    if normalized_content_type and normalized_content_type not in {"image/png", "image/x-png"}:
        raise ValueError("Only PNG uploads are supported. Please upload a PNG file.")

    content = file.file.read()
    if not content:
        raise ValueError("Uploaded image is empty")
    if not content.startswith(PNG_SIGNATURE):
        raise ValueError("Only PNG uploads are supported. Please upload a PNG file.")

    filename = f"product_{product_id}_{int(datetime.utcnow().timestamp() * 1000)}_{sort_order}.{IMAGE_UPLOAD_FORMAT}"
    destination = UPLOAD_DIR / filename
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    except OSError as exc:
        raise ValueError(f"Unable to save uploaded image: {exc}") from exc

    url = f"/uploads/{filename}"
    return ProductImage(product_id=product_id, url=url, is_primary=is_primary, sort_order=sort_order)


def normalize_upload_files(images: Optional[Union[UploadFile, List[UploadFile]]]) -> List[UploadFile]:
    if not images:
        return []
    if isinstance(images, list):
        return images
    return [images]


def create_product(
    db: Session,
    sku: str,
    name: str,
    category: str,
    description: str,
    price: Decimal,
    lock_duration_days: int,
    delivery_options: str,
    inventory_quantity: int,
    images: Optional[Union[UploadFile, List[UploadFile]]],
) -> Product:
    product = Product(
        sku=sku,
        name=name,
        description=description,
        price=price,
        slug=slugify(name),
        category=category or "Emergency Kits",
        image="/assets/images/no_image.png",
        stock_quantity=max(inventory_quantity, 0),
        inflation_savings=Decimal("0"),
        storage_type="pantry",
        reserve_lock_price=price,
        locked_price=price,
        lock_duration_days=min(max(lock_duration_days, 10), 100),
        feeds_people=4,
        reserve_days=min(max(lock_duration_days, 10), 100),
        rating=4.7,
        delivery_options=delivery_options,
        metadata_json={"category": category or "Emergency Kits", "source": "admin"},
    )
    db.add(product)
    db.flush()
    image_files = normalize_upload_files(images)
    for index, image in enumerate(image_files[:4]):
        is_primary = index == 0
        saved_image = save_product_image(image, product.id, is_primary=is_primary, sort_order=index)
        product.images.append(saved_image)
        if is_primary:
            product.image = saved_image.url
    if not product.image:
        product.image = "/assets/images/no_image.png"
    inventory = Inventory(product=product, quantity=max(inventory_quantity, 0), reserved_quantity=0, incoming_quantity=0)
    db.add(inventory)
    db.commit()
    db.refresh(product)
    return product


def update_product(
    db: Session,
    product: Product,
    name: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    price: Optional[Decimal] = None,
    lock_duration_days: Optional[int] = None,
    delivery_options: Optional[str] = None,
    inventory_quantity: Optional[int] = None,
    images: Optional[Union[UploadFile, List[UploadFile]]] = None,
) -> Product:
    if name is not None:
        product.name = name
        product.slug = slugify(name)
    if category is not None:
        product.category = category
        existing_meta = product.metadata_json or {}
        product.metadata_json = {**existing_meta, "category": category}
    if description is not None:
        product.description = description
    if price is not None:
        product.price = price
        product.reserve_lock_price = price
        product.locked_price = price
    if lock_duration_days is not None:
        product.lock_duration_days = min(max(lock_duration_days, 10), 100)
        product.reserve_days = product.lock_duration_days
    if delivery_options is not None:
        product.delivery_options = delivery_options
    if inventory_quantity is not None:
        product.stock_quantity = max(inventory_quantity, 0)
        if not product.inventory:
            product.inventory = Inventory(quantity=max(inventory_quantity, 0), reserved_quantity=0, incoming_quantity=0)
        else:
            product.inventory.quantity = max(inventory_quantity, 0)
    image_files = normalize_upload_files(images)
    if image_files:
        for image in image_files[:4]:
            saved_image = save_product_image(image, product.id, is_primary=False, sort_order=len(product.images))
            product.images.append(saved_image)
        if product.images:
            product.image = product.images[-1].url
    if not product.image:
        product.image = "/assets/images/no_image.png"
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product: Product) -> None:
    db.delete(product)
    db.commit()


def get_cart_summary(cart: Cart) -> dict:
    item_list = []
    total = Decimal("0.00")
    for item in cart.items:
        if item.product is None:
            continue
        item_total = Decimal(item.price_snapshot) * item.quantity
        total += item_total
        item_list.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "name": item.product.name,
                "quantity": item.quantity,
                "unit_price": to_serializable(item.price_snapshot),
                "total_price": to_serializable(item_total),
                "reserve_option": item.reserve_option,
                "partial_delivery": item.partial_delivery,
            }
        )
    return {"id": cart.id, "user_id": cart.user_id, "status": cart.status, "items": item_list, "total_amount": to_serializable(total)}


def add_or_update_cart_item(
    db: Session,
    cart: Cart,
    product: Product,
    quantity: int,
    reserve_option: str = "purchase",
    partial_delivery: bool = False,
    lock_duration_days: int = 100,
) -> CartItem:
    item = None
    for existing in cart.items:
        if existing.product_id == product.id and existing.reserve_option == reserve_option and existing.partial_delivery == partial_delivery:
            item = existing
            break
    if item is None:
        item = CartItem(
            cart=cart,
            product=product,
            quantity=max(quantity, 1),
            price_snapshot=product.price,
            reserve_option=reserve_option,
            partial_delivery=partial_delivery,
            lock_duration_days=min(max(lock_duration_days, 10), 100),
        )
        db.add(item)
    else:
        item.quantity = max(item.quantity + quantity, 1)
        item.price_snapshot = product.price
        item.lock_duration_days = min(max(lock_duration_days, item.lock_duration_days), 100)
    db.commit()
    db.refresh(item)
    return item


def create_order_from_cart(
    db: Session,
    user: UserProfile,
    cart: Cart,
    payment_method: str = "supabase-google",
    payment_intent_id: str | None = None,
    metadata: dict | None = None,
) -> Order:
    total_amount = Decimal("0.00")
    order = Order(
        user=user,
        order_number=f"FV-{int(datetime.utcnow().timestamp())}-{user.id}",
        status="confirmed",
        payment_status="confirmed",
        order_type="purchase",
        metadata_json=metadata or {},
    )
    db.add(order)
    db.flush()

    for item in cart.items:
        if not item.product:
            continue
        item_total = Decimal(item.price_snapshot) * item.quantity
        total_amount += item_total
        order_item = OrderItem(
            order=order,
            product=item.product,
            quantity=item.quantity,
            unit_price=item.price_snapshot,
            total_price=item_total,
            reserve_type=item.reserve_option,
            partial_delivery=item.partial_delivery,
        )
        db.add(order_item)
        inventory = item.product.inventory
        if not inventory:
            inventory = Inventory(product=item.product, quantity=0, reserved_quantity=0)
            db.add(inventory)
        if item.reserve_option == "purchase":
            inventory.quantity = max(inventory.quantity - item.quantity, 0)
        else:
            inventory.reserved_quantity += item.quantity
            inventory.quantity = max(inventory.quantity - item.quantity, 0)

    order.total_amount = total_amount
    payment = Payment(
        order=order,
        amount=total_amount,
        currency="USD",
        status="confirmed",
        payment_method=payment_method,
        transaction_ref=payment_intent_id or f"pay_{datetime.utcnow().timestamp()}_{user.id}",
        metadata_json=metadata or {},
    )
    db.add(payment)
    db.flush()

    if payment_intent_id:
        payment_transaction = PaymentTransaction(
            payment_id=payment.id,
            stripe_payment_intent_id=payment_intent_id,
            status="succeeded",
            amount=total_amount,
            currency="USD",
            payment_method=payment_method,
            metadata_json=metadata or {},
        )
        db.add(payment_transaction)

    cart.status = "checked_out"
    db.commit()
    db.refresh(order)
    return order


def create_reserve_vault(
    db: Session,
    user: UserProfile,
    items: List[dict],
    payment_method: str = "supabase-google",
) -> ReserveVault:
    vault = ReserveVault(user=user, status="pending_payment", total_value=Decimal("0.00"), upfront_paid=Decimal("0.00"))
    db.add(vault)
    db.flush()
    total_value = Decimal("0.00")
    upfront_paid = Decimal("0.00")
    reserve_items: List[ReserveItem] = []
    for item_payload in items:
        product_id = int(item_payload.get("product_id"))
        quantity = int(item_payload.get("quantity", 1))
        reserve_type = item_payload.get("reserve_type", "deposit")
        partial_delivery = bool(item_payload.get("partial_delivery", False))
        product = db.query(Product).filter(Product.id == product_id, Product.is_active.is_(True)).one_or_none()
        if not product:
            continue
        unit_price = product.price
        total_price = Decimal(unit_price) * quantity
        deposit_rate = Decimal("0.15") if reserve_type == "deposit" else Decimal("0.20")
        deposit_paid = (total_price * deposit_rate).quantize(Decimal("0.01"))
        total_value += total_price
        upfront_paid += deposit_paid
        lock_expires_at = datetime.utcnow() + timedelta(days=int(product.lock_duration_days or 100))
        lifecycle_metadata = build_reserve_lifecycle_metadata(
            product=product,
            quantity=quantity,
            total_value=total_price,
            deposit_paid=deposit_paid,
            partial_delivery=partial_delivery,
            lock_expires_at=lock_expires_at,
        )
        reserve_item = ReserveItem(
            reserve_vault=vault,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            deposit_paid=deposit_paid,
            reserve_type=reserve_type,
            partial_delivery=partial_delivery,
            delivery_split={"deposit_rate": float(deposit_rate), "partial_delivery": partial_delivery},
            metadata_json=lifecycle_metadata,
            status="pending_payment",
        )
        db.add(reserve_item)
        db.flush()
        ownership_percent = int((deposit_paid / total_price) * Decimal("100")) if total_price else 0
        ownership_percent = max(1, min(100, ownership_percent))
        position = ReservePosition(
            user=user,
            product=product,
            reserve_vault=vault,
            reserved_quantity=quantity,
            locked_price=unit_price,
            total_value=total_price,
            deposit_paid=deposit_paid,
            ownership_percent=ownership_percent,
            remaining_balance=max(Decimal("0.00"), total_price - deposit_paid),
            lock_expires_at=lock_expires_at,
            status="pending_payment",
            metadata_json=lifecycle_metadata,
        )
        db.add(position)
        db.flush()
        schedule_now = DeliverySchedule(
            reserve_item=reserve_item,
            scheduled_date=datetime.utcnow(),
            quantity=quantity if not partial_delivery else quantity // 2,
            notes="Initial delivery scheduled when reserve is created.",
        )
        db.add(schedule_now)
        if partial_delivery:
            future_date = datetime.utcnow() + timedelta(days=30)
            schedule_future = DeliverySchedule(
                reserve_item=reserve_item,
                scheduled_date=future_date,
                quantity=max(quantity - schedule_now.quantity, 0),
                notes="Future reserve delivery for locked inventory.",
            )
            db.add(schedule_future)
        inventory = product.inventory
        if not inventory:
            inventory = Inventory(product=product, quantity=0, reserved_quantity=0, incoming_quantity=0)
            db.add(inventory)
        inventory.quantity = max(inventory.quantity - quantity, 0)
        inventory.reserved_quantity += quantity
        reserve_items.append(reserve_item)

    vault.total_value = total_value
    vault.upfront_paid = Decimal("0.00")
    vault.locked_until = datetime.utcnow() + timedelta(days=100)
    vault.next_delivery_date = min((schedule.scheduled_date for item in reserve_items for schedule in item.schedules), default=None)
    vault.metadata_json = {
        **(vault.metadata_json or {}),
        "reservation": {
            "lock_percent": 15,
            "lock_duration_days": 100,
            "reservation_type": "inventory_lock",
            "partial_delivery_enabled": any(item.partial_delivery for item in reserve_items),
            "locked_until": vault.locked_until.isoformat(),
        },
        "payment_status": "pending",
        "payment_verified": False,
        "delivery": {
            "partial_delivered_percent": 0,
            "remaining_locked_percent": 100,
            "delivery_status": "partial_active" if any(item.partial_delivery for item in reserve_items) else "scheduled",
        },
    }
    vault.health_score = calculate_reserve_health_score(vault)
    db.commit()
    db.refresh(vault)

    if total_value > 0:
        order = Order(
            user=user,
            order_number=f"RV-{int(datetime.utcnow().timestamp())}-{user.id}",
            status="pending",
            payment_status="pending",
            order_type="reserve",
            total_amount=Decimal("0.00"),
        )
        db.add(order)
        db.flush()
        payment = Payment(
            order=order,
            amount=Decimal("0.00"),
            currency="USD",
            status="pending",
            payment_method=payment_method,
            transaction_ref=f"reserve_{datetime.utcnow().timestamp()}_{user.id}",
        )
        db.add(payment)
        db.commit()
    return vault


def build_reserve_lifecycle_metadata(
    product: Product,
    quantity: int,
    total_value: Decimal,
    deposit_paid: Decimal,
    partial_delivery: bool,
    lock_expires_at: datetime,
) -> dict:
    ownership_percent = int((deposit_paid / total_value) * Decimal("100")) if total_value else 0
    ownership_percent = min(100, max(0, ownership_percent))
    metadata = {
        "reservation": {
            "lock_percent": 15,
            "ownership_percent": ownership_percent,
            "lock_duration_days": int(product.lock_duration_days or 100),
            "locked_until": lock_expires_at.isoformat(),
            "reservation_type": "inventory_lock",
            "partial_delivery_enabled": bool(partial_delivery),
        },
        "delivery": {
            "partial_delivered_percent": 0,
            "remaining_locked_percent": 100,
            "delivery_status": "partial_active" if partial_delivery else "scheduled",
        },
    }
    return metadata


def get_user_reserve_positions(db: Session, user: UserProfile) -> List[ReservePosition]:
    return (
        db.query(ReservePosition)
        .filter(
            ReservePosition.user_id == user.id,
            ReservePosition.status != "pending_payment",
        )
        .order_by(ReservePosition.created_at.desc())
        .all()
    )


def apply_reserve_payment(db: Session, user: UserProfile, position_id: int, amount: Decimal) -> ReservePosition:
    position = db.query(ReservePosition).filter(ReservePosition.id == position_id, ReservePosition.user_id == user.id).one_or_none()
    if not position:
        raise ValueError("Reserve position not found")

    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= Decimal("0.00"):
        raise ValueError("Payment amount must be positive")

    position.deposit_paid = min(position.total_value, position.deposit_paid + amount).quantize(Decimal("0.01"))
    position.remaining_balance = max(Decimal("0.00"), position.total_value - position.deposit_paid).quantize(Decimal("0.01"))
    ownership_percent = int((position.deposit_paid / position.total_value) * Decimal("100")) if position.total_value else 0
    ownership_percent = min(100, max(0, ownership_percent))
    position.ownership_percent = ownership_percent
    position.status = "fully_owned" if position.ownership_percent >= 100 else "partially_funded"

    payment_events = list(position.metadata_json.get("payment_events") or [])
    payment_events.append({
        "type": "payment",
        "amount": float(amount),
        "timestamp": datetime.utcnow().isoformat(),
        "percent": position.ownership_percent,
    })
    position.metadata_json["payment_events"] = payment_events
    position.metadata_json["payment_verified"] = True
    position.metadata_json["reservation"]["ownership_percent"] = position.ownership_percent
    position.metadata_json["delivery"]["remaining_locked_percent"] = max(0, 100 - position.metadata_json["delivery"].get("partial_delivered_percent", 0))

    if position.reserve_vault:
        position.reserve_vault.status = "active"
        position.reserve_vault.upfront_paid = sum((item.deposit_paid or Decimal("0.00")) for item in position.reserve_vault.reserve_positions).quantize(Decimal("0.01"))
        position.reserve_vault.metadata_json["payment_status"] = "paid"
        position.reserve_vault.metadata_json["payment_verified"] = True
        position.reserve_vault.metadata_json["payment_events"] = payment_events
        position.reserve_vault.health_score = calculate_reserve_health_score(position.reserve_vault)
        for reserve_item in position.reserve_vault.reserve_items:
            reserve_item.status = position.status
            reserve_item.metadata_json["payment_events"] = payment_events
            reserve_item.metadata_json["payment_verified"] = True

    db.commit()
    db.refresh(position)
    return position


def request_partial_delivery(db: Session, user: UserProfile, position_id: int, delivery_percent: int) -> ReservePosition:
    position = db.query(ReservePosition).filter(ReservePosition.id == position_id, ReservePosition.user_id == user.id).one_or_none()
    if not position:
        raise ValueError("Reserve position not found")

    delivery_percent = max(0, min(int(delivery_percent), 100))
    position.metadata_json["delivery"]["partial_delivered_percent"] = delivery_percent
    position.metadata_json["delivery"]["remaining_locked_percent"] = max(0, 100 - delivery_percent)
    position.metadata_json["delivery"]["delivery_status"] = "partial_active" if delivery_percent < 100 else "complete"
    position.status = "partially_delivered" if delivery_percent < 100 else "fully_owned"

    if position.reserve_vault and position.product_id:
        reserve_item = db.query(ReserveItem).filter(ReserveItem.reserve_vault_id == position.reserve_vault_id, ReserveItem.product_id == position.product_id).one_or_none()
        if reserve_item:
            reserve_item.partial_delivery = True
            reserve_item.status = position.status
            reserve_item.metadata_json = {
                **(reserve_item.metadata_json or {}),
                "delivery": position.metadata_json["delivery"],
                "reservation": position.metadata_json["reservation"],
            }
            delivery_schedule = DeliverySchedule(
                reserve_item=reserve_item,
                scheduled_date=datetime.utcnow(),
                quantity=max(1, int(round(position.reserved_quantity * (delivery_percent / 100.0)))),
                status="scheduled" if delivery_percent < 100 else "delivered",
                notes=f"Partial delivery requested: {delivery_percent}% of reserve.",
            )
            db.add(delivery_schedule)

    db.commit()
    db.refresh(position)
    return position


def calculate_reserve_health_score(vault: ReserveVault) -> int:
    if not vault.locked_until:
        return 75
    remaining = (vault.locked_until - datetime.utcnow()).days
    score = 80 + min(max(remaining, 0), 20)
    return int(min(score, 100))


def build_dashboard_data(db: Session, user: UserProfile) -> dict:
    active_reserves = db.query(ReserveVault).filter(ReserveVault.user_id == user.id, ReserveVault.status == "active").all()
    orders = db.query(Order).filter(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(10).all()
    notifications = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(10).all()

    total_reserved_value = sum([rv.total_value for rv in active_reserves])
    total_items_reserved = sum(
        sum(item.quantity for item in rv.reserve_items)
        for rv in active_reserves
    )
    next_delivery_date = None
    reserve_health_scores = []
    for rv in active_reserves:
        if rv.next_delivery_date and (not next_delivery_date or rv.next_delivery_date < next_delivery_date):
            next_delivery_date = rv.next_delivery_date
        if rv.health_score is not None:
            reserve_health_scores.append(rv.health_score)

    average_health_score = int(sum(reserve_health_scores) / len(reserve_health_scores)) if reserve_health_scores else 0
    days_of_supply = int(total_items_reserved / 4) if total_items_reserved else 0
    price_lock_savings = sum([(rv.total_value - rv.upfront_paid) for rv in active_reserves])

    recent_months = []
    today = datetime.utcnow().date()
    base_month = datetime(today.year, today.month, 1)
    for offset in range(5, -1, -1):
        month_start = (base_month - timedelta(days=offset * 30)).replace(day=1)
        recent_months.append(month_start)

    consumption_series = []
    savings_series = []
    for month_start in recent_months:
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        reserved_count = sum(
            item.quantity
            for rv in active_reserves
            for item in rv.reserve_items
            if item.created_at and month_start <= item.created_at < next_month
        )
        consumed_count = sum(
            item.quantity
            for order in db.query(Order).filter(Order.user_id == user.id, Order.created_at >= month_start, Order.created_at < next_month).all()
            for item in order.items
            if order.order_type == "purchase"
        )
        savings_amount = sum(
            (rv.total_value - rv.upfront_paid)
            for rv in active_reserves
            if rv.created_at and month_start <= rv.created_at < next_month
        )
        consumption_series.append(
            {
                "month": month_start.strftime("%b"),
                "reserved": int(reserved_count),
                "consumed": int(consumed_count),
            }
        )
        savings_series.append(
            {
                "month": month_start.strftime("%b"),
                "saved": float(savings_amount),
            }
        )

    alerts = []
    for notification in notifications:
        alerts.append(
            {
                "type": notification.type,
                "msg": notification.message,
                "title": notification.title,
                "is_read": notification.is_read,
            }
        )

    for rv in active_reserves:
        if rv.locked_until:
            days_left = (rv.locked_until.date() - today).days
            if days_left <= 14:
                alerts.append(
                    {
                        "type": "expiry",
                        "msg": f"{rv.metadata_json.get('label', 'Reserve')} is due in {days_left} days. Review your delivery or top-up schedule.",
                        "severity": "warning",
                    }
                )

    order_timeline = []
    for order in orders[:4]:
        order_timeline.append(
            {
                "id": order.order_number,
                "label": order.metadata_json.get("description") or f"Order #{order.order_number}",
                "status": order.status.upper(),
                "date": to_serializable(order.created_at),
                "color": (
                    "bg-emerald-500"
                    if order.status.lower() == "delivered"
                    else "bg-blue-500"
                    if order.status.lower() == "shipped"
                    else "bg-violet-500"
                    if order.status.lower() == "reserved"
                    else "bg-gray-400"
                ),
            }
        )

    return {
        "user": model_to_dict(user),
        "active_reserves": [model_to_dict(rv, include_relationships=True) for rv in active_reserves],
        "order_history": [model_to_dict(order, include_relationships=True) for order in orders],
        "notifications": [model_to_dict(note) for note in notifications],
        "reserve_summary": {
            "total_reserved_value": to_serializable(total_reserved_value),
            "total_items_reserved": total_items_reserved,
            "days_of_supply": days_of_supply,
            "next_delivery_date": to_serializable(next_delivery_date),
            "active_reserve_count": len(active_reserves),
            "health_score": average_health_score,
            "price_lock_savings": to_serializable(price_lock_savings),
        },
        "consumption_series": consumption_series,
        "savings_series": savings_series,
        "alerts": alerts,
        "order_timeline": order_timeline,
    }


def fetch_admin_analytics(db: Session) -> dict:
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    today_start = datetime(now.year, now.month, now.day)

    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    products = db.query(Product).all()
    inventory_items = db.query(Inventory).all()
    reserve_vaults = db.query(ReserveVault).all()
    users = db.query(UserProfile).all()
    payments = db.query(Payment).order_by(Payment.created_at.desc()).limit(10).all()

    total_orders = len(orders)
    total_revenue = sum((order.total_amount or Decimal("0.00")) for order in orders)
    orders_today = sum(1 for order in orders if order.created_at and order.created_at >= today_start)
    orders_this_month = sum(1 for order in orders if order.created_at and order.created_at >= month_start)
    total_inventory = sum(item.quantity or 0 for item in inventory_items)
    total_reserved = sum(item.reserved_quantity or 0 for item in inventory_items)
    low_stock_products = [
        product
        for product in products
        if (product.inventory and (product.inventory.quantity or 0) <= int((product.metadata_json or {}).get("reorder_threshold", 10)))
    ]
    active_reserves = [vault for vault in reserve_vaults if vault.status == "active"]
    reserve_value = sum((vault.total_value or Decimal("0.00")) for vault in active_reserves)

    trend_months = []
    base_month = datetime(now.year, now.month, 1)
    for offset in range(5, -1, -1):
        month = (base_month - timedelta(days=offset * 30)).replace(day=1)
        next_month = (month + timedelta(days=32)).replace(day=1)
        month_orders = [order for order in orders if order.created_at and month <= order.created_at < next_month]
        month_users = [user for user in users if user.created_at and user.created_at < next_month]
        trend_months.append(
            {
                "month": month.strftime("%b"),
                "orders": len(month_orders),
                "revenue": to_serializable(sum((order.total_amount or Decimal("0.00")) for order in month_orders)),
                "customers": len(month_users),
            }
        )

    product_performance = []
    for product in products:
        quantity_sold = sum(item.quantity for item in product.order_items if item.order and item.order.status != "failed")
        revenue = sum((item.total_price or Decimal("0.00")) for item in product.order_items if item.order and item.order.status != "failed")
        product_performance.append(
            {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "category": product.category,
                "quantity_sold": int(quantity_sold),
                "revenue": to_serializable(revenue),
                "stock": product.inventory.quantity if product.inventory else product.stock_quantity,
            }
        )
    product_performance.sort(key=lambda item: item["revenue"], reverse=True)

    return {
        "orders": int(total_orders),
        "revenue": to_serializable(total_revenue),
        "orders_today": int(orders_today),
        "orders_this_month": int(orders_this_month),
        "inventory_on_hand": int(total_inventory),
        "inventory_reserved": int(total_reserved),
        "customer_count": int(len(users)),
        "active_users": int(sum(1 for user in users if user.role != "admin")),
        "active_reserve_count": int(len(active_reserves)),
        "reserve_value": to_serializable(reserve_value),
        "low_stock_count": int(len(low_stock_products)),
        "payment_confirmed": int(sum(1 for order in orders if order.payment_status == "confirmed")),
        "payment_pending": int(sum(1 for order in orders if order.payment_status == "pending")),
        "order_trends": trend_months,
        "revenue_trends": trend_months,
        "customer_growth": trend_months,
        "low_stock_products": [serialize_product(product) for product in low_stock_products[:8]],
        "product_performance": product_performance[:8],
        "recent_transactions": [
            {
                **model_to_dict(payment),
                "order": model_to_dict(payment.order) if payment.order else None,
            }
            for payment in payments
        ],
    }


def build_order_confirmation_email(order: Order, payment: Optional[Payment] = None) -> tuple[str, str, str]:
    lines = []
    for item in getattr(order, "items", []) or []:
        product = getattr(item, "product", None)
        product_name = getattr(product, "name", "Product") or "Product"
        quantity = getattr(item, "quantity", 1) or 1
        total_price = getattr(item, "total_price", Decimal("0")) or Decimal("0")
        reserve_type = getattr(item, "reserve_type", "purchase") or "purchase"
        lock_duration = getattr(product, "lock_duration_days", None)
        duration_text = f"{int(lock_duration)} days" if lock_duration else "standard reservation window"
        lines.append(
            f"<li><strong>{int(quantity)}x {product_name}</strong> — ${float(total_price):.2f} ({reserve_type}) • Reserve/lock duration: {duration_text}</li>"
        )

    if not lines:
        lines.append("<li>Order items will appear here after confirmation.</li>")

    max_lock_days = max(
        [int(getattr(item.product, "lock_duration_days", 0) or 0) for item in getattr(order, "items", []) if getattr(item, "product", None)],
        default=0,
    )
    duration_summary = f"up to {max_lock_days} days" if max_lock_days else "standard reservation window"

    amount = getattr(payment, "amount", None)
    if amount is None:
        amount = getattr(order, "total_amount", Decimal("0"))
    amount_value = float(amount or Decimal("0"))
    order_number = getattr(order, "order_number", None) or f"#{getattr(order, 'id', 'unknown')}"

    subject = "FoodVault Order Confirmation"
    html_body = (
        "<html><body style='font-family: Arial, sans-serif; color: #1f2937;'>"
        "<p>Thank you for your purchase. Your order has been confirmed.</p>"
        f"<p><strong>Order ID:</strong> {order_number}</p>"
        f"<p><strong>Total Paid:</strong> ${amount_value:.2f}</p>"
        "<p><strong>Items:</strong></p>"
        f"<ul>{''.join(lines)}</ul>"
        f"<p><strong>Reserve/Lock Duration:</strong> {duration_summary}</p>"
        "<p>We’ll keep you updated on your order status and fulfillment.</p>"
        "</body></html>"
    )
    text_body = (
        "Thank you for your purchase. Your order has been confirmed.\n"
        f"Order ID: {order_number}\n"
        f"Total Paid: ${amount_value:.2f}\n"
        "Items:\n"
        + "\n".join([line.replace("<strong>", "").replace("</strong>", "").replace("<li>", "- ").replace("</li>", "") for line in lines])
        + "\n"
        f"Reserve/Lock Duration: {duration_summary}\n"
        "We’ll keep you updated on your order status and fulfillment."
    )
    return subject, html_body, text_body


async def send_order_confirmation_email(order: Order, payment: Optional[Payment] = None) -> bool:
    user = getattr(order, "user", None)
    to_email = getattr(user, "email", None) if user else None
    if not to_email:
        logger.warning("Order %s has no email address available for confirmation", getattr(order, "id", None))
        return False

    logger.info("Starting order confirmation email send for order %s to %s", getattr(order, "id", None), to_email)
    subject, html_body, text_body = build_order_confirmation_email(order, payment)
    sent = await asyncio.to_thread(send_email, to_email, subject, html_body, text_body)
    if not sent:
        logger.warning("Failed to send order confirmation email for order %s", getattr(order, "id", None))
        return False

    logger.info("Order confirmation email sent for order %s", getattr(order, "id", None))
    return True


def send_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    smtp_host = os.getenv("SMTP_HOST") or os.getenv("EMAIL_HOST")
    smtp_port_raw = os.getenv("SMTP_PORT") or os.getenv("EMAIL_PORT") or "587"
    smtp_user = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER")
    smtp_password = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASSWORD")
    email_from = os.getenv("EMAIL_FROM") or os.getenv("SMTP_FROM") or os.getenv("EMAIL_SENDER") or "no-reply@foodvault.example"

    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        logger.warning("Invalid SMTP port configured (%s); using default 587", smtp_port_raw)
        smtp_port = 587

    missing = []
    if not smtp_host:
        missing.append("SMTP_HOST/EMAIL_HOST")
    if not smtp_user:
        missing.append("SMTP_USER/EMAIL_USER")
    if not smtp_password:
        missing.append("SMTP_PASSWORD/EMAIL_PASSWORD")

    if missing:
        logger.warning("SMTP email service is not configured; missing %s; skipping email to %s", ", ".join(missing), to_email)
        return False

    logger.info("Sending email via SMTP to %s from %s", to_email, email_from)
    message = [
        f"From: {email_from}",
        f"To: {to_email}",
        f"Subject: {subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/html; charset=utf-8",
        "",
        html_body,
    ]
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.sendmail(email_from, [to_email], "\r\n".join(message))
        logger.info("Email sent successfully to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def notify_user(db: Session, user: UserProfile, title: str, message: str, notification_type: str = "system") -> Notification:
    notification = Notification(user=user, title=title, message=message, type=notification_type)
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification
