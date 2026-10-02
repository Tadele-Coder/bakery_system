from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    User,
    Category,
    Product,
    Ingredient,
    Recipe,
    RecipeIngredient,
    Production,
    ProductionItem,
    Sale,
    SaleItem,
    Payment,
    Customer,
    SpecialOrder,
    SpecialOrderItem,
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    fieldsets = UserAdmin.fieldsets + (
        ("Bakery Role", {
            "fields": ("role",),
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Bakery Role", {
            "fields": ("role",),
        }),
    )

    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "role",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "first_name",
        "last_name",
        "email",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "category",
        "price",
        "is_available",
        "created_at",
    )

    list_filter = (
        "category",
        "is_available",
    )

    search_fields = (
        "name",
        "description",
    )


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "unit",
        "current_stock",
        "minimum_stock",
        "cost_per_unit",
        "is_active",
    )

    list_filter = (
        "unit",
        "is_active",
    )

    search_fields = (
        "name",
    )


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):

    list_display = (
        "product",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "product__name",
    )

    inlines = [
        RecipeIngredientInline,
    ]


@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):

    list_display = (
        "recipe",
        "ingredient",
        "quantity",
    )

    list_filter = (
        "ingredient",
    )

    search_fields = (
        "recipe__product__name",
        "ingredient__name",
    )


class ProductionItemInline(admin.TabularInline):
    model = ProductionItem
    extra = 1


@admin.register(Production)
class ProductionAdmin(admin.ModelAdmin):

    list_display = (
        "production_date",
        "status",
        "created_by",
        "started_at",
        "completed_at",
    )

    list_filter = (
        "status",
        "production_date",
    )

    search_fields = (
        "notes",
        "created_by__username",
    )

    date_hierarchy = "production_date"

    inlines = [
        ProductionItemInline,
    ]


@admin.register(ProductionItem)
class ProductionItemAdmin(admin.ModelAdmin):

    list_display = (
        "production",
        "product",
        "planned_quantity",
        "actual_quantity",
    )

    search_fields = (
        "product__name",
    )


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):

    list_display = (
        "sale_number",
        "sale_date",
        "cashier",
        "subtotal",
        "discount",
        "total_amount",
        "payment_status",
    )

    list_filter = (
        "payment_status",
        "sale_date",
    )

    search_fields = (
        "sale_number",
        "cashier__username",
    )

    date_hierarchy = "sale_date"

    inlines = [
        SaleItemInline,
    ]


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):

    list_display = (
        "sale",
        "product",
        "quantity",
        "unit_price",
        "total_price",
    )

    search_fields = (
        "sale__sale_number",
        "product__name",
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):

    list_display = (
        "sale",
        "method",
        "amount",
        "reference_number",
        "status",
        "payment_date",
        "recorded_by",
    )

    list_filter = (
        "method",
        "status",
        "payment_date",
    )

    search_fields = (
        "sale__sale_number",
        "reference_number",
        "recorded_by__username",
    )

    date_hierarchy = "payment_date"


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "phone",
        "email",
        "created_at",
    )

    search_fields = (
        "name",
        "phone",
        "email",
    )


class SpecialOrderItemInline(admin.TabularInline):
    model = SpecialOrderItem
    extra = 1


@admin.register(SpecialOrder)
class SpecialOrderAdmin(admin.ModelAdmin):

    list_display = (
        "order_number",
        "customer",
        "event_type",
        "event_date",
        "status",
        "total_amount",
        "deposit_amount",
        "created_by",
    )

    list_filter = (
        "event_type",
        "status",
        "event_date",
    )

    search_fields = (
        "order_number",
        "customer__name",
        "customer__phone",
    )

    date_hierarchy = "event_date"

    inlines = [
        SpecialOrderItemInline,
    ]


@admin.register(SpecialOrderItem)
class SpecialOrderItemAdmin(admin.ModelAdmin):

    list_display = (
        "special_order",
        "product",
        "quantity",
        "unit_price",
        "total_price",
    )

    search_fields = (
        "special_order__order_number",
        "product__name",
    )