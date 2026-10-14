from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        CASHIER = "CASHIER", "Cashier"
        PRODUCTION_MANAGER = "PRODUCTION_MANAGER", "Production Manager"

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.CASHIER,
    )

    def __str__(self):
        return self.username


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
    )

    is_available = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Ingredient(models.Model):

    class Unit(models.TextChoices):
        KG = "KG", "Kilogram"
        GRAM = "GRAM", "Gram"
        LITER = "LITER", "Liter"
        ML = "ML", "Milliliter"
        PIECE = "PIECE", "Piece"

    name = models.CharField(max_length=150, unique=True)

    unit = models.CharField(
        max_length=20,
        choices=Unit.choices,
    )

    current_stock = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=0,
    )

    minimum_stock = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=0,
    )

    cost_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class StockMovement(models.Model):

    class MovementType(models.TextChoices):
        RECEIVED = "RECEIVED", "Stock Received"
        USED = "USED", "Stock Used"
        ADJUSTMENT = "ADJUSTMENT", "Stock Adjustment"

    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )

    production = models.ForeignKey(
        "Production",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
    )

    note = models.TextField(
        blank=True,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.ingredient.name} - "
            f"{self.get_movement_type_display()} - "
            f"{self.quantity}"
        )


class Recipe(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="recipe",
    )

    description = models.TextField(
        blank=True,
        help_text="General instructions for preparing this product.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Recipe - {self.product.name}"


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="ingredients",
    )

    ingredient = models.ForeignKey(
        Ingredient,
        on_delete=models.PROTECT,
        related_name="recipe_items",
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
    )

    class Meta:
        ordering = ["ingredient__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "ingredient"],
                name="unique_recipe_ingredient",
            )
        ]

    def __str__(self):
        return (
            f"{self.recipe.product.name} - "
            f"{self.ingredient.name} - "
            f"{self.quantity} {self.ingredient.unit}"
        )

class Production(models.Model):

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    production_date = models.DateField()
    special_order = models.OneToOneField(
        "SpecialOrder",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="production",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNED,
    )

    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="productions_created",
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    stock_deducted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-production_date", "-created_at"]

    def __str__(self):
        return f"Production - {self.production_date}"


class ProductionItem(models.Model):
    production = models.ForeignKey(
        Production,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="production_items",
    )

    planned_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    actual_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["product__name"]

    def __str__(self):
        return (
            f"{self.product.name} - "
            f"Planned: {self.planned_quantity}, "
            f"Actual: {self.actual_quantity}"
        )

class Sale(models.Model):

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially Paid"
        PAID = "PAID", "Paid"
        REFUNDED = "REFUNDED", "Refunded"

    sale_number = models.CharField(
        max_length=30,
        unique=True,
    )

    sale_date = models.DateTimeField(
        auto_now_add=True,
    )

    cashier = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="sales",
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-sale_date"]

    def __str__(self):
        return self.sale_number


class SaleItem(models.Model):
    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="sale_items",
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        ordering = ["product__name"]

    def __str__(self):
        return f"{self.product.name} × {self.quantity}"


class Payment(models.Model):

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        TELEBIRR = "TELEBIRR", "Telebirr"
        BANK = "BANK", "Bank"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    # Payment for a regular sale
    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="payments",
        null=True,
        blank=True,
    )

    # Payment for a special order
    special_order = models.ForeignKey(
        "SpecialOrder",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    method = models.CharField(
        max_length=20,
        choices=Method.choices,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    reference_number = models.CharField(
        max_length=100,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    payment_date = models.DateTimeField(
        auto_now_add=True,
    )

    notes = models.TextField(blank=True)

    recorded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="payments_recorded",
    )

    class Meta:
        ordering = ["-payment_date"]

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        sale__isnull=False,
                        special_order__isnull=True,
                    )
                    | models.Q(
                        sale__isnull=True,
                        special_order__isnull=False,
                    )
                ),
                name="payment_one_transaction_only",
            ),
        ]

    def __str__(self):
        return f"{self.method} - {self.amount} ETB"


class Customer(models.Model):
    name = models.CharField(max_length=150)

    phone = models.CharField(max_length=30)

    email = models.EmailField(
        blank=True,
    )

    address = models.TextField(
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} - {self.phone}"


class SpecialOrder(models.Model):

    class EventType(models.TextChoices):
        BIRTHDAY = "BIRTHDAY", "Birthday"
        WEDDING = "WEDDING", "Wedding"
        GRADUATION = "GRADUATION", "Graduation"
        ANNIVERSARY = "ANNIVERSARY", "Anniversary"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        IN_PRODUCTION = "IN_PRODUCTION", "In Production"
        READY = "READY", "Ready"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(
        max_length=30,
        unique=True,
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="special_orders",
    )

    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
    )

    event_date = models.DateField()

    pickup_time = models.TimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    deposit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    notes = models.TextField(
        blank=True,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="special_orders_created",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["event_date", "-created_at"]

    def __str__(self):
        return self.order_number


class SpecialOrderItem(models.Model):
    special_order = models.ForeignKey(
        SpecialOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="special_order_items",
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    customization = models.TextField(
        blank=True,
        help_text="Special design, flavor, size, decoration, message, etc.",
    )

    class Meta:
        ordering = ["product__name"]

    def __str__(self):
        return (
            f"{self.product.name} × "
            f"{self.quantity}"
        )

class BusinessSettings(models.Model):

    business_name = models.CharField(
        max_length=150,
        default="Bakery Management",
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    address = models.TextField(
        blank=True,
    )

    logo = models.ImageField(
        upload_to="business/",
        blank=True,
        null=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.business_name