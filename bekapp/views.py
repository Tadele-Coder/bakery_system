import csv
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from reportlab.lib import colors
from openpyxl.drawing.image import Image as ExcelImage
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import (
    getSampleStyleSheet,
    ParagraphStyle,
)
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
)
from django.http import HttpResponse
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404

from django.db.models import (
    Sum,
    Q,
    OuterRef,
    Subquery,
    DecimalField,
    Value,
    ExpressionWrapper,
    F,
)

from django.db.models.functions import (
    Coalesce,
    Greatest,
)

from django.http import JsonResponse

from django.db.models.deletion import ProtectedError

from django.contrib.auth import authenticate, login, logout

from django.utils import timezone

from django.db import transaction

from django.core.exceptions import ValidationError

from .forms import (
    SaleItemForm,
    PaymentForm,
    CustomerForm,
    SpecialOrderForm,
    SpecialOrderItemForm,
    RecipeForm,
    RecipeIngredientForm,
    StaffCreateForm,
    StaffEditForm,
    ProductForm,
    IngredientForm,
    StockMovementForm,
    BusinessSettingsForm,
)

from .models import (
    Product,
    User,
    Production,
    ProductionItem,
    Recipe,
    RecipeIngredient,
    Ingredient,
    Sale,
    SaleItem,
    Payment,
    Customer,
    SpecialOrder,
    SpecialOrderItem,
    StockMovement,
    BusinessSettings,
)


@transaction.atomic
def deduct_production_stock(production, user):
    """
    Safely deduct ingredient stock for a production.

    Protects against duplicate deductions, checks all required
    ingredients before changing stock, and records stock movements.
    """

    # Lock the production record so concurrent requests cannot
    # independently process the same production.
    production = Production.objects.select_for_update().get(
        pk=production.pk
    )

    if production.stock_deducted:
        return

    if production.status != Production.Status.IN_PROGRESS:
        raise ValidationError(
            "Only in-progress production can deduct ingredient stock."
        )

    items = list(
        production.items.select_related("product").all()
    )

    required_quantities = {}

    # Calculate the total quantity required for each ingredient.
    for item in items:
        actual_quantity = item.actual_quantity

        if actual_quantity <= 0:
            continue

        try:
            recipe = item.product.recipe
        except Recipe.DoesNotExist:
            raise ValidationError(
                f"{item.product.name} does not have a recipe. "
                "Create a recipe before completing production."
            )

        recipe_items = recipe.ingredients.select_related(
            "ingredient"
        ).all()

        if not recipe_items.exists():
            raise ValidationError(
                f"The recipe for {item.product.name} has no ingredients."
            )

        for recipe_item in recipe_items:
            ingredient_id = recipe_item.ingredient_id
            quantity = recipe_item.quantity * actual_quantity

            required_quantities[ingredient_id] = (
                required_quantities.get(
                    ingredient_id,
                    Decimal("0.000"),
                ) + quantity
            )

    if not required_quantities:
        raise ValidationError(
            "No ingredient quantities were calculated for this production."
        )

    # Lock all required ingredients in a consistent order.
    # This helps prevent concurrent stock deductions from overspending stock.
    ingredients = {
        ingredient.pk: ingredient
        for ingredient in Ingredient.objects.select_for_update()
        .filter(pk__in=required_quantities.keys())
        .order_by("pk")
    }

    if len(ingredients) != len(required_quantities):
        raise ValidationError(
            "One or more required ingredients could not be found."
        )

    # Validate every ingredient before changing any stock.
    for ingredient_id, required_quantity in required_quantities.items():
        ingredient = ingredients[ingredient_id]

        if ingredient.current_stock < required_quantity:
            raise ValidationError(
                f"Insufficient stock for {ingredient.name}. "
                f"Available: {ingredient.current_stock} "
                f"{ingredient.get_unit_display()}, "
                f"Required: {required_quantity} "
                f"{ingredient.get_unit_display()}."
            )

    production_description = ", ".join(
        f"{item.product.name} ({item.actual_quantity})"
        for item in items
        if item.actual_quantity > 0
    )

    # Deduct stock and create movement records atomically.
    movements = []

    for ingredient_id, required_quantity in required_quantities.items():
        ingredient = ingredients[ingredient_id]

        ingredient.current_stock -= required_quantity
        ingredient.save(
            update_fields=["current_stock", "updated_at"]
        )

        movements.append(
            StockMovement(
                ingredient=ingredient,
                production=production,
                movement_type=StockMovement.MovementType.USED,
                quantity=required_quantity,
                note=(
                    f"Used for Production #{production.id} - "
                    f"{production_description}"
                ),
                created_by=user,
            )
        )

    StockMovement.objects.bulk_create(movements)

    production.stock_deducted = True
    production.save(
        update_fields=["stock_deducted", "updated_at"]
    )

def home(request):
    return render(request, 'bekapp/home.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            return redirect('dashboard')

        return render(
            request,
            'bekapp/login.html',
            {'error': 'Invalid username or password.'}
        )

    return render(request, 'bekapp/login.html')


def logout_view(request):
    logout(request)
    return redirect('home')

def dashboard(request):
    """
    Redirect the logged-in user to the dashboard
    according to their role.
    """

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role == 'OWNER':
        return redirect('owner_dashboard')

    elif request.user.role == 'PRODUCTION_MANAGER':
        return redirect('production_dashboard')

    elif request.user.role == 'CASHIER':
        return redirect('cashier_dashboard')

    return redirect('home')


def owner_dashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    # ---------------------------------------------------------
    # OUTSTANDING BALANCES FROM REGULAR SALES
    # ---------------------------------------------------------

    outstanding_sales = Sale.objects.exclude(
        payment_status=Sale.PaymentStatus.PAID
    ).prefetch_related('payments')

    outstanding_sales_amount = Decimal('0.00')

    for sale in outstanding_sales:
        paid_amount = sum(
            (
                payment.amount
                for payment in sale.payments.all()
                if payment.status == Payment.Status.PAID
            ),
            Decimal('0.00')
        )

        remaining_amount = sale.total_amount - paid_amount

        if remaining_amount > 0:
            outstanding_sales_amount += remaining_amount

    # ---------------------------------------------------------
    # OUTSTANDING BALANCES FROM SPECIAL ORDERS
    # ---------------------------------------------------------

    special_orders = SpecialOrder.objects.exclude(
        status=SpecialOrder.Status.CANCELLED
    ).prefetch_related('payments')

    outstanding_special_orders_amount = Decimal('0.00')

    for special_order in special_orders:
        paid_payments = [
            payment
            for payment in special_order.payments.all()
            if payment.status == Payment.Status.PAID
        ]

        paid_amount = sum(
            (payment.amount for payment in paid_payments),
            Decimal('0.00')
        )

        # Check whether the deposit has already been recorded
        # as a separate paid payment.
        deposit_payment_recorded = any(
            (payment.notes or '').startswith(
                f"Deposit for special order "
                f"{special_order.order_number}"
            )
            for payment in paid_payments
        )

        # Include saved deposits that do not have a separate
        # payment transaction, without counting them twice.
        if (
            special_order.deposit_amount > 0
            and not deposit_payment_recorded
        ):
            paid_amount += special_order.deposit_amount

        remaining_amount = (
            special_order.total_amount - paid_amount
        )

        if remaining_amount > 0:
            outstanding_special_orders_amount += remaining_amount

    # ---------------------------------------------------------
    # COMBINED OUTSTANDING BALANCE
    # ---------------------------------------------------------

    outstanding_payment_total = (
        outstanding_sales_amount
        + outstanding_special_orders_amount
    )

    # ---------------------------------------------------------
    # INGREDIENT STOCK SUMMARY
    # ---------------------------------------------------------

    active_ingredients = Ingredient.objects.filter(
        is_active=True
    )

    ingredient_count = active_ingredients.count()

    low_stock_count = active_ingredients.filter(
        current_stock__gt=0,
        current_stock__lt=F('minimum_stock'),
    ).count()

    out_of_stock_count = active_ingredients.filter(
        current_stock__lte=0
    ).count()

    # ---------------------------------------------------------
    # DASHBOARD CONTEXT
    # ---------------------------------------------------------

    context = {
        'product_count': Product.objects.filter(
            is_available=True
        ).count(),

        'today_production_count': Production.objects.filter(
            production_date=today
        ).count(),

        'today_sale_count': Sale.objects.filter(
            sale_date__date=today
        ).count(),

        'outstanding_payment_total': outstanding_payment_total,

        # Ingredient Stock Summary
        'ingredient_count': ingredient_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
    }

    return render(
        request,
        'bekapp/owner_dashboard.html',
        context
    )


def production_dashboard(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'PRODUCTION_MANAGER':
        return redirect('dashboard')

    today = timezone.localdate()

    # ---------------------------------------------------------
    # FINISHED PRODUCT STOCK
    # ---------------------------------------------------------

    produced_quantity_subquery = ProductionItem.objects.filter(
        product=OuterRef('pk'),
        production__status=Production.Status.COMPLETED
    ).values(
        'product'
    ).annotate(
        total=Sum('actual_quantity')
    ).values(
        'total'
    )

    sold_quantity_subquery = SaleItem.objects.filter(
        product=OuterRef('pk')
    ).values(
        'product'
    ).annotate(
        total=Sum('quantity')
    ).values(
        'total'
    )

    products = Product.objects.filter(
        is_available=True
    ).annotate(

        produced_quantity=Coalesce(
            Subquery(
                produced_quantity_subquery,
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            ),
            Value(
                Decimal('0.00'),
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            )
        ),

        sold_quantity=Coalesce(
            Subquery(
                sold_quantity_subquery,
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            ),
            Value(
                Decimal('0.00'),
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            )
        ),

    ).annotate(

        available_stock_raw=ExpressionWrapper(
            F('produced_quantity') - F('sold_quantity'),
            output_field=DecimalField(
                max_digits=12,
                decimal_places=2
            )
        ),

    ).annotate(

        available_stock=Greatest(
            F('available_stock_raw'),
            Value(
                Decimal('0.00'),
                output_field=DecimalField(
                    max_digits=12,
                    decimal_places=2
                )
            )
        )

    ).order_by(
        'name'
    )

    # ---------------------------------------------------------
    # DASHBOARD CONTEXT
    # ---------------------------------------------------------

    context = {

        'product_count': Product.objects.count(),

        'today_production_count': Production.objects.filter(
            production_date=today
        ).count(),

        'completed_production_count': Production.objects.filter(
            status=Production.Status.COMPLETED
        ).count(),

        'recipe_count': Recipe.objects.count(),

        'stock_products': products,

    }

    return render(
        request,
        'bekapp/production_dashboard.html',
        context
    )



def production_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'PRODUCTION_MANAGER']:
        return redirect('dashboard')

    productions = Production.objects.select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    return render(
        request,
        'bekapp/production_list.html',
        {
            'productions': productions,
        }
    )

def production_completed_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'PRODUCTION_MANAGER']:
        return redirect('dashboard')

    productions = Production.objects.filter(
        status=Production.Status.COMPLETED
    ).select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    ).order_by(
        '-production_date',
        '-id'
    )

    return render(
        request,
        'bekapp/production_completed_list.html',
        {
            'productions': productions,
        }
    )

def production_stock_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'PRODUCTION_MANAGER']:
        return redirect('dashboard')

    produced_quantity_subquery = ProductionItem.objects.filter(
        product=OuterRef('pk'),
        production__status=Production.Status.COMPLETED
    ).values(
        'product'
    ).annotate(
        total=Sum('actual_quantity')
    ).values(
        'total'
    )

    sold_quantity_subquery = SaleItem.objects.filter(
        product=OuterRef('pk')
    ).values(
        'product'
    ).annotate(
        total=Sum('quantity')
    ).values(
        'total'
    )

    products = Product.objects.filter(
        is_available=True
    ).annotate(
        produced_quantity=Subquery(
            produced_quantity_subquery
        ),
        sold_quantity=Subquery(
            sold_quantity_subquery
        )
    ).order_by(
        'name'
    )

    for product in products:
        produced = product.produced_quantity or 0
        sold = product.sold_quantity or 0

        product.available_stock = produced - sold

    return render(
        request,
        'bekapp/production_stock_list.html',
        {
            'products': products,
        }
    )


def production_create(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'PRODUCTION_MANAGER':
        return redirect('dashboard')

    products = Product.objects.filter(
        is_available=True
    ).prefetch_related(
        'recipe__ingredients__ingredient'
    )

    if request.method == 'POST':

        production_date = request.POST.get('production_date')
        status = request.POST.get('status')
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product')
        planned_quantities = request.POST.getlist('planned_quantity')
        actual_quantities = request.POST.getlist('actual_quantity')
        item_notes = request.POST.getlist('item_notes')

        with transaction.atomic():

            production = Production.objects.create(
                production_date=production_date,
                status=status,
                notes=notes,
                created_by=request.user,
            )

            for index, product_id in enumerate(product_ids):

                if not product_id:
                    continue

                planned_quantity = planned_quantities[index]

                if not planned_quantity:
                    continue

                actual_quantity = (
                    actual_quantities[index]
                    if index < len(actual_quantities)
                    else ''
                )

                item_note = (
                    item_notes[index]
                    if index < len(item_notes)
                    else ''
                )

                ProductionItem.objects.create(
                    production=production,
                    product_id=product_id,
                    planned_quantity=planned_quantity,
                    actual_quantity=actual_quantity or 0,
                    notes=item_note,
                )

        return redirect('production_list')

    return render(
        request,
        'bekapp/production_create.html',
        {
            'products': products,
            'status_choices': Production.Status.choices,
        }
    )

def production_start(request, production_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'PRODUCTION_MANAGER':
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect(
            'production_detail',
            production_id=production_id
        )

    production = Production.objects.get(
        id=production_id
    )

    if production.status == Production.Status.PLANNED:

        production.status = Production.Status.IN_PROGRESS
        production.started_at = timezone.now()

        production.save(
            update_fields=[
                'status',
                'started_at',
                'updated_at',
            ]
        )

    return redirect(
        'production_detail',
        production_id=production.id
    )



def production_complete(request, production_id):
    if not request.user.is_authenticated:
        return redirect("login")

    if request.user.role != "PRODUCTION_MANAGER":
        return redirect("dashboard")

    production = Production.objects.select_related(
        "special_order"
    ).prefetch_related(
        "items__product__recipe__ingredients__ingredient"
    ).get(id=production_id)

    if production.status != Production.Status.IN_PROGRESS:
        return redirect(
            "production_detail",
            production_id=production.id,
        )

    if request.method == "POST":
        try:
            with transaction.atomic():

                # Lock and refresh the production record.
                production = Production.objects.select_for_update().get(
                    pk=production_id
                )

                if production.status != Production.Status.IN_PROGRESS:
                    raise ValidationError(
                        "This production is no longer in progress."
                    )

                items = list(
                    production.items.select_related("product").all()
                )

                # Validate and save actual production quantities.
                for item in items:
                    actual_quantity = request.POST.get(
                        f"actual_quantity_{item.id}"
                    )

                    item_notes = request.POST.get(
                        f"item_notes_{item.id}", ""
                    ).strip()

                    if actual_quantity in (None, ""):
                        raise ValidationError(
                            f"Please enter the actual quantity "
                            f"for {item.product.name}."
                        )

                    from decimal import Decimal, InvalidOperation

                    try:
                        actual_quantity = Decimal(actual_quantity)
                    except (InvalidOperation, ValueError):
                        raise ValidationError(
                            f"Invalid actual quantity for "
                            f"{item.product.name}."
                        )

                    if not actual_quantity.is_finite():
                        raise ValidationError(
                            f"Invalid actual quantity for "
                            f"{item.product.name}."
                        )

                    if actual_quantity <= 0:
                        raise ValidationError(
                            f"Actual quantity for {item.product.name} "
                            f"must be greater than zero."
                        )

                    item.actual_quantity = actual_quantity
                    item.notes = item_notes

                    item.save(
                        update_fields=[
                            "actual_quantity",
                            "notes",
                        ]
                    )

                # Deduct ingredient stock safely.
                deduct_production_stock(production, request.user)

                # Mark production as completed.
                production.status = Production.Status.COMPLETED
                production.completed_at = timezone.now()

                production.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "updated_at",
                    ]
                )

                # Automatically mark the linked special order READY.
                if production.special_order_id:
                    special_order = (
                        SpecialOrder.objects.select_for_update().get(
                            pk=production.special_order_id
                        )
                    )

                    if (
                        special_order.status
                        == SpecialOrder.Status.IN_PRODUCTION
                    ):
                        special_order.status = (
                            SpecialOrder.Status.READY
                        )

                        special_order.save(
                            update_fields=[
                                "status",
                                "updated_at",
                            ]
                        )

            return redirect(
                "production_detail",
                production_id=production.id,
            )

        except ValidationError as error:
            production.refresh_from_db()

            return render(
                request,
                "bekapp/production_complete.html",
                {
                    "production": production,
                    "stock_error": error.message,
                },
            )

    return render(
        request,
        "bekapp/production_complete.html",
        {
            "production": production,
        },
    )


def production_cancel(request, production_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'PRODUCTION_MANAGER':
        return redirect('dashboard')

    production = Production.objects.get(
        id=production_id
    )

    # Only Planned production can be cancelled.
    if production.status != Production.Status.PLANNED:
        return redirect(
            'production_detail',
            production_id=production.id
        )

    if request.method == 'POST':

        production.status = Production.Status.CANCELLED

        production.save(
            update_fields=[
                'status',
                'updated_at',
            ]
        )

        return redirect(
            'production_detail',
            production_id=production.id
        )

    return render(
        request,
        'bekapp/production_cancel.html',
        {
            'production': production,
        }
    )

def production_detail(request, production_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'PRODUCTION_MANAGER', 'CASHIER']:
        return redirect('dashboard')

    production = Production.objects.select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    ).get(
        id=production_id
    )

    return render(
        request,
        'bekapp/production_detail.html',
        {
            'production': production,
        }
    )


def cashier_dashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'CASHIER':
        return redirect('dashboard')

    today = timezone.localdate()

    # Today's sales
    today_sales_count = Sale.objects.filter(
        sale_date__date=today
    ).count()

    # Today's payments
    today_payments = Payment.objects.filter(
        payment_date__date=today
    )

    today_payment_count = today_payments.count()

    # Payments successfully received today
    completed_payment_count = Payment.objects.filter(
        payment_date__date=today,
        status=Payment.Status.PAID
    ).count()

    # Outstanding balances from regular sales
    outstanding_sales = Sale.objects.exclude(
        payment_status=Sale.PaymentStatus.PAID
    ).prefetch_related('payments')

    outstanding_sales_amount = Decimal('0.00')

    for sale in outstanding_sales:
        paid_amount = sum(
            (
                payment.amount
                for payment in sale.payments.all()
                if payment.status == Payment.Status.PAID
            ),
            Decimal('0.00')
        )

        remaining_amount = sale.total_amount - paid_amount

        if remaining_amount > 0:
            outstanding_sales_amount += remaining_amount

    # Outstanding balances from special orders
    special_orders = SpecialOrder.objects.exclude(
        status=SpecialOrder.Status.CANCELLED
    ).prefetch_related('payments')

    outstanding_special_orders_amount = Decimal('0.00')

    for special_order in special_orders:
        paid_payments = [
            payment
            for payment in special_order.payments.all()
            if payment.status == Payment.Status.PAID
        ]

        paid_amount = sum(
            (payment.amount for payment in paid_payments),
            Decimal('0.00')
        )

        # Support older orders whose deposit was saved on the order
        # but was not recorded as a separate Payment transaction.
        deposit_payment_recorded = any(
            (payment.notes or '').startswith(
                f"Deposit for special order {special_order.order_number}"
            )
            for payment in paid_payments
        )

        if (
            special_order.deposit_amount > 0
            and not deposit_payment_recorded
        ):
            paid_amount += special_order.deposit_amount

        remaining_amount = (
            special_order.total_amount - paid_amount
        )

        if remaining_amount > 0:
            outstanding_special_orders_amount += remaining_amount

    # Combined outstanding balance
    outstanding_amount = (
        outstanding_sales_amount
        + outstanding_special_orders_amount
    )

    context = {
        'today_sales_count': today_sales_count,
        'today_payment_count': today_payment_count,
        'completed_payment_count': completed_payment_count,
        'outstanding_amount': outstanding_amount,
    }

    return render(
        request,
        'bekapp/cashier_dashboard.html',
        context
    )


def sale_create(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'CASHIER':
        return redirect('dashboard')

    # ---------------------------------------------------------
    # CALCULATE FINISHED PRODUCT STOCK
    # ---------------------------------------------------------

    produced_quantity_subquery = ProductionItem.objects.filter(
        product=OuterRef('pk'),
        production__status=Production.Status.COMPLETED
    ).values(
        'product'
    ).annotate(
        total=Sum('actual_quantity')
    ).values(
        'total'
    )

    sold_quantity_subquery = SaleItem.objects.filter(
        product=OuterRef('pk')
    ).values(
        'product'
    ).annotate(
        total=Sum('quantity')
    ).values(
        'total'
    )

    products = Product.objects.filter(
        is_available=True
    ).annotate(

        produced_quantity=Coalesce(
            Subquery(
                produced_quantity_subquery,
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            ),
            Value(
                Decimal('0.00'),
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            )
        ),

        sold_quantity=Coalesce(
            Subquery(
                sold_quantity_subquery,
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            ),
            Value(
                Decimal('0.00'),
                output_field=DecimalField(
                    max_digits=10,
                    decimal_places=2
                )
            )
        ),

    ).annotate(

        available_stock_raw=ExpressionWrapper(
            F('produced_quantity') - F('sold_quantity'),
            output_field=DecimalField(
                max_digits=12,
                decimal_places=2
            )
        ),

    ).annotate(

        available_stock=Greatest(
            F('available_stock_raw'),
            Value(
                Decimal('0.00'),
                output_field=DecimalField(
                    max_digits=12,
                    decimal_places=2
                )
            )
        ),

    ).order_by(
        'name'
    )

    # ---------------------------------------------------------
    # CREATE SALE
    # ---------------------------------------------------------

    if request.method == 'POST':

        form = SaleItemForm(request.POST)

        # Give the form the stock-annotated products.
        form.fields['product'].queryset = products

        if form.is_valid():

            product = form.cleaned_data['product']
            quantity = form.cleaned_data['quantity']

            # Recalculate stock from the database.
            produced_quantity = ProductionItem.objects.filter(
                product=product,
                production__status=Production.Status.COMPLETED
            ).aggregate(
                total=Sum('actual_quantity')
            )['total'] or Decimal('0.00')

            sold_quantity = SaleItem.objects.filter(
                product=product
            ).aggregate(
                total=Sum('quantity')
            )['total'] or Decimal('0.00')

            available_stock = (
                produced_quantity - sold_quantity
            )

            sellable_stock = max(
                available_stock,
                Decimal('0.00')
            )

            # Prevent selling more than available stock.
            if quantity > sellable_stock:

                form.add_error(
                    'quantity',
                    f'Insufficient stock for {product.name}. '
                    f'Available stock: {sellable_stock:.2f}.'
                )

            else:

                unit_price = product.price

                total_price = (
                    quantity * unit_price
                )

                today = timezone.localdate()

                sale_count = Sale.objects.filter(
                    sale_date__date=today
                ).count() + 1

                sale_number = (
                    f"SALE-{today.strftime('%Y%m%d')}-"
                    f"{sale_count:04d}"
                )

                with transaction.atomic():

                    sale = Sale.objects.create(
                        sale_number=sale_number,
                        cashier=request.user,
                        subtotal=total_price,
                        discount=Decimal('0.00'),
                        total_amount=total_price,
                    )

                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        total_price=total_price,
                    )

                return redirect(
                    'sale_detail',
                    sale_id=sale.id
                )

    else:

        form = SaleItemForm()

        # Give the form the stock-annotated products.
        form.fields['product'].queryset = products

    return render(
        request,
        'bekapp/sale_create.html',
        {
            'form': form,
        }
    )

def sale_detail(request, sale_id):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'CASHIER']:
        return redirect('dashboard')

    sale = Sale.objects.prefetch_related(
        'items__product',
        'payments',
    ).get(
        id=sale_id
    )

    # ---------------------------------------------------------
    # CALCULATE SUCCESSFUL PAYMENTS
    # ---------------------------------------------------------

    paid_amount = sale.payments.filter(
        status=Payment.Status.PAID
    ).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    # ---------------------------------------------------------
    # CALCULATE REMAINING BALANCE
    # ---------------------------------------------------------

    remaining_amount = (
        sale.total_amount - paid_amount
    )

    if remaining_amount < Decimal('0.00'):
        remaining_amount = Decimal('0.00')

    return render(
        request,
        'bekapp/sale_detail.html',
        {
            'sale': sale,
            'paid_amount': paid_amount,
            'remaining_amount': remaining_amount,
        }
    )

def payment_create(request, sale_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'CASHIER':
        return redirect('dashboard')

    sale = Sale.objects.prefetch_related(
        'payments',
    ).get(
        id=sale_id
    )

    # Calculate payments already successfully paid.
    paid_amount = sum(
        payment.amount
        for payment in sale.payments.filter(
            status=Payment.Status.PAID
        )
    )

    # Calculate the remaining amount.
    remaining_amount = (
        sale.total_amount - paid_amount
    )
    if remaining_amount <= 0:
        return redirect(
        'sale_detail',
        sale_id=sale.id
    )

    if request.method == 'POST':

        form = PaymentForm(request.POST)

        if form.is_valid():

            amount = form.cleaned_data['amount']

            # Do not allow payment greater than
            # the remaining sale balance.
            if amount > remaining_amount:

                form.add_error(
                    'amount',
                    f'Payment cannot be greater than '
                    f'the remaining balance of '
                    f'{remaining_amount:.2f} ETB.'
                )

            else:

                with transaction.atomic():

                    Payment.objects.create(
                        sale=sale,
                        method=form.cleaned_data['method'],
                        amount=amount,
                        reference_number=form.cleaned_data[
                            'reference_number'
                        ],
                        status=Payment.Status.PAID,
                        notes=form.cleaned_data['notes'],
                        recorded_by=request.user,
                    )

                    new_paid_amount = (
                        paid_amount + amount
                    )

                    if new_paid_amount >= sale.total_amount:

                        sale.payment_status = (
                            Sale.PaymentStatus.PAID
                        )

                    else:

                        sale.payment_status = (
                            Sale.PaymentStatus.PARTIAL
                        )

                    sale.save(
                        update_fields=[
                            'payment_status',
                            'updated_at',
                        ]
                    )

                return redirect(
                    'sale_detail',
                    sale_id=sale.id
                )

    else:

        form = PaymentForm(
            initial={
                'amount': remaining_amount,
            }
        )

    return render(
        request,
        'bekapp/payment_create.html',
        {
            'sale': sale,
            'form': form,
            'paid_amount': paid_amount,
            'remaining_amount': remaining_amount,
        }
    )


def payment_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER'
    ]:
        return redirect('dashboard')

    payments = Payment.objects.select_related(
        'sale',
        'special_order',
        'recorded_by',
    ).all()

    # Today's payments
    if request.GET.get('today') == '1':
        today = timezone.localdate()

        payments = payments.filter(
            payment_date__date=today
        )

    # Today's completed/paid payments
    elif request.GET.get('completed_today') == '1':
        today = timezone.localdate()

        payments = payments.filter(
            payment_date__date=today,
            status='PAID'
        )

    return render(
        request,
        'bekapp/payment_list.html',
        {
            'payments': payments,
        }
    )


def special_order_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'CASHIER', 'PRODUCTION_MANAGER']:
        return redirect('dashboard')

    special_orders = SpecialOrder.objects.select_related(
        'customer',
        'created_by'
    ).all()

    return render(
        request,
        'bekapp/special_order_list.html',
        {
            'special_orders': special_orders,
        }
    )


def payment_history(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'CASHIER']:
        return redirect('dashboard')

    payments = Payment.objects.select_related(
        'sale',
        'special_order',
        'recorded_by',
    ).order_by(
        '-payment_date'
    )

    return render(
        request,
        'bekapp/payment_history.html',
        {
            'payments': payments,
        }
    )


def outstanding_payments(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER',
    ]:
        return redirect('dashboard')

    # ==========================================
    # REGULAR SALES OUTSTANDING PAYMENTS
    # ==========================================

    sales = Sale.objects.prefetch_related(
        'payments'
    ).exclude(
        payment_status=Sale.PaymentStatus.PAID
    ).order_by(
        '-sale_date'
    )

    outstanding_sales = []

    for sale in sales:
        paid_amount = sum(
            (
                payment.amount
                for payment in sale.payments.all()
                if payment.status == Payment.Status.PAID
            ),
            Decimal('0.00'),
        )

        remaining_amount = sale.total_amount - paid_amount

        if remaining_amount > 0:
            outstanding_sales.append({
                'sale': sale,
                'paid_amount': paid_amount,
                'remaining_amount': remaining_amount,
            })

    # ==========================================
    # SPECIAL ORDER OUTSTANDING PAYMENTS
    # ==========================================

    special_orders = SpecialOrder.objects.exclude(
        status=SpecialOrder.Status.CANCELLED
    ).select_related(
        'customer',
        'created_by',
    ).prefetch_related(
        'payments'
    ).order_by(
        '-created_at'
    )

    outstanding_special_orders = []

    for special_order in special_orders:
        payments = list(special_order.payments.all())

        paid_payments = [
            payment
            for payment in payments
            if payment.status == Payment.Status.PAID
        ]

        paid_amount = sum(
            (
                payment.amount
                for payment in paid_payments
            ),
            Decimal('0.00'),
        )

        # Support older orders whose deposit was stored on the
        # order but not yet recorded as a Payment.
        deposit_payment_recorded = any(
            payment.notes.startswith(
                f"Deposit for special order {special_order.order_number}"
            )
            for payment in paid_payments
        )

        if (
            special_order.deposit_amount > 0
            and not deposit_payment_recorded
        ):
            paid_amount += special_order.deposit_amount

        remaining_amount = (
            special_order.total_amount - paid_amount
        )

        if remaining_amount > 0:
            outstanding_special_orders.append({
                'special_order': special_order,
                'paid_amount': paid_amount,
                'remaining_amount': remaining_amount,
            })

    return render(
        request,
        'bekapp/outstanding_payments.html',
        {
            'outstanding_sales': outstanding_sales,
            'outstanding_special_orders': (
                outstanding_special_orders
            ),
        }
    )


def sale_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER'
    ]:
        return redirect('dashboard')

    sales = Sale.objects.select_related(
        'cashier',
    ).prefetch_related(
        'items',
        'payments',
    ).order_by(
        '-sale_date'
    )

    return render(
        request,
        'bekapp/sale_list.html',
        {
            'sales': sales,
        }
    )

def cashier_product_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER'
    ]:
        return redirect('dashboard')

    products = Product.objects.select_related(
        'category',
    ).filter(
        is_available=True
    ).order_by(
        'category__name',
        'name'
    )

    return render(
        request,
        'bekapp/cashier_product_list.html',
        {
            'products': products,
        }
    )

def production_special_order_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'PRODUCTION_MANAGER'
    ]:
        return redirect('dashboard')

    special_orders = SpecialOrder.objects.filter(
        status__in=[
            SpecialOrder.Status.CONFIRMED,
            SpecialOrder.Status.IN_PRODUCTION,
            SpecialOrder.Status.READY,
        ]
    ).select_related(
        'customer',
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    return render(
        request,
        'bekapp/production_special_order_list.html',
        {
            'special_orders': special_orders,
        }
    )


def special_order_confirm(request, special_order_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER'
    ]:
        return redirect('dashboard')

    special_order = SpecialOrder.objects.get(
        id=special_order_id
    )

    if special_order.status != SpecialOrder.Status.PENDING:
        return redirect(
            'special_order_detail',
            special_order_id=special_order.id
        )

    if request.method == 'POST':

        special_order.status = SpecialOrder.Status.CONFIRMED

        special_order.save(
            update_fields=[
                'status',
                'updated_at',
            ]
        )

    return redirect(
        'special_order_detail',
        special_order_id=special_order.id
    )

def special_order_start_production(request, special_order_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'PRODUCTION_MANAGER']:
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect(
            'special_order_detail',
            special_order_id=special_order_id,
        )

    with transaction.atomic():
        special_order = SpecialOrder.objects.select_for_update().get(
            id=special_order_id
        )

        if special_order.status != SpecialOrder.Status.CONFIRMED:
            return redirect(
                'special_order_detail',
                special_order_id=special_order.id,
            )

        # Reuse an existing linked production record if one exists.
        production = Production.objects.filter(
            special_order=special_order
        ).first()

        if production is None:
            order_items = list(special_order.items.select_related('product'))

            if not order_items:
                raise ValidationError(
                    "Cannot start production because this special order "
                    "has no items."
                )

            production = Production.objects.create(
                production_date=timezone.localdate(),
                status=Production.Status.IN_PROGRESS,
                special_order=special_order,
                created_by=request.user,
                started_at=timezone.now(),
                notes=f"Production for special order "
                      f"{special_order.order_number}",
            )

            for order_item in order_items:
                ProductionItem.objects.create(
                    production=production,
                    product=order_item.product,
                    planned_quantity=order_item.quantity,
                    actual_quantity=0,
                    notes=order_item.customization,
                )

        else:
            # Do not restart completed, cancelled, or already
            # in-progress production.
            if production.status != Production.Status.PLANNED:
                return redirect(
                    'special_order_detail',
                    special_order_id=special_order.id,
                )

            production.status = Production.Status.IN_PROGRESS
            production.started_at = timezone.now()
            production.save(
                update_fields=[
                    'status',
                    'started_at',
                    'updated_at',
                ]
            )

        special_order.status = SpecialOrder.Status.IN_PRODUCTION
        special_order.save(update_fields=['status', 'updated_at'])

    return redirect(
        'production_detail',
        production_id=production.id,
    )


def special_order_mark_ready(request, special_order_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'PRODUCTION_MANAGER']:
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect(
            'special_order_detail',
            special_order_id=special_order_id,
        )

    special_order = SpecialOrder.objects.get(
        id=special_order_id
    )

    # Production completion automatically marks the order READY.
    # Never allow this view to bypass production completion.
    if special_order.status != SpecialOrder.Status.IN_PRODUCTION:
        return redirect(
            'special_order_detail',
            special_order_id=special_order.id,
        )

    production = Production.objects.filter(
        special_order=special_order
    ).first()

    if (
        production is None
        or production.status != Production.Status.COMPLETED
        or not production.stock_deducted
    ):
        return redirect(
            'special_order_detail',
            special_order_id=special_order.id,
        )

    special_order.status = SpecialOrder.Status.READY
    special_order.save(
        update_fields=['status', 'updated_at']
    )

    return redirect(
        'special_order_detail',
        special_order_id=special_order.id,
    )



def special_order_complete(request, special_order_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in ['OWNER', 'CASHIER']:
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect(
            'special_order_detail',
            special_order_id=special_order_id
        )

    with transaction.atomic():
        special_order = get_object_or_404(
            SpecialOrder.objects.select_for_update(),
            id=special_order_id
        )

        # Only Ready orders can be completed.
        if special_order.status != SpecialOrder.Status.READY:
            return redirect(
                'special_order_detail',
                special_order_id=special_order.id
            )

        # Calculate actual successful payments.
        paid_payments = list(
            Payment.objects.filter(
                special_order=special_order,
                status=Payment.Status.PAID
            )
        )

        paid_amount = sum(
            (payment.amount for payment in paid_payments),
            Decimal('0.00')
        )

        # Include a legacy deposit only if its payment record is missing.
        deposit_note = (
            f"Deposit for special order {special_order.order_number}"
        )

        deposit_recorded = any(
            (payment.notes or '').startswith(deposit_note)
            for payment in paid_payments
        )

        if (
            special_order.deposit_amount > 0
            and not deposit_recorded
        ):
            paid_amount += special_order.deposit_amount

        remaining_amount = max(
            Decimal('0.00'),
            special_order.total_amount - paid_amount
        )

        # Never complete an order with an outstanding balance.
        if remaining_amount > 0:
            return redirect(
                'special_order_detail',
                special_order_id=special_order.id
            )

        special_order.status = SpecialOrder.Status.COMPLETED

        special_order.save(
            update_fields=['status', 'updated_at']
        )

    return redirect(
        'special_order_detail',
        special_order_id=special_order.id
    )


def special_order_create(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER',
        'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    products = Product.objects.filter(
        is_available=True
    ).order_by('name')

    if request.method == 'POST':
        customer_form = CustomerForm(request.POST)
        order_form = SpecialOrderForm(request.POST)

        product_ids = request.POST.getlist('product')
        quantities = request.POST.getlist('quantity')
        customizations = request.POST.getlist('customization')

        if customer_form.is_valid() and order_form.is_valid():
            item_data = []
            total_amount = Decimal('0.00')

            for index, product_id in enumerate(product_ids):
                if not product_id or index >= len(quantities):
                    continue

                quantity_value = quantities[index]

                if not quantity_value:
                    continue

                try:
                    quantity = Decimal(quantity_value)
                except (InvalidOperation, TypeError):
                    continue

                if not quantity.is_finite() or quantity <= 0:
                    continue

                try:
                    product = Product.objects.get(
                        id=product_id,
                        is_available=True,
                    )
                except (
                    Product.DoesNotExist,
                    ValueError,
                    TypeError,
                ):
                    continue

                unit_price = product.price
                total_price = unit_price * quantity

                customization = ''
                if index < len(customizations):
                    customization = customizations[index].strip()

                item_data.append({
                    'product': product,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'customization': customization,
                })

                total_amount += total_price

            if not item_data:
                order_form.add_error(
                    None,
                    'Please add at least one valid product to the special order.',
                )

            else:
                deposit_amount = (
                    order_form.cleaned_data.get('deposit_amount')
                    or Decimal('0.00')
                )

                if deposit_amount > total_amount:
                    order_form.add_error(
                        'deposit_amount',
                        'Deposit cannot be greater than the order total.',
                    )

                else:
                    with transaction.atomic():
                        customer = customer_form.save()

                        special_order = order_form.save(commit=False)
                        special_order.customer = customer
                        special_order.created_by = request.user
                        special_order.total_amount = total_amount

                        # Generate a unique order number safely.
                        last_order = (
                            SpecialOrder.objects
                            .select_for_update()
                            .order_by('-id')
                            .first()
                        )

                        next_number = (
                            last_order.id + 1
                            if last_order
                            else 1
                        )

                        special_order.order_number = (
                            f"ORD-{next_number:04d}"
                        )

                        special_order.save()

                        for item in item_data:
                            SpecialOrderItem.objects.create(
                                special_order=special_order,
                                product=item['product'],
                                quantity=item['quantity'],
                                unit_price=item['unit_price'],
                                total_price=item['total_price'],
                                customization=item['customization'],
                            )

                        # Record the deposit as an actual payment.
                        if deposit_amount > 0:
                            Payment.objects.create(
                                special_order=special_order,
                                method=order_form.cleaned_data[
                                    'deposit_method'
                                ],
                                amount=deposit_amount,
                                reference_number=(
                                    order_form.cleaned_data.get(
                                        'deposit_reference_number'
                                    ) or ''
                                ).strip(),
                                status=Payment.Status.PAID,
                                notes=(
                                    f"Deposit for special order "
                                    f"{special_order.order_number}"
                                ),
                                recorded_by=request.user,
                            )

                    return redirect(
                        'special_order_detail',
                        special_order_id=special_order.id,
                    )

    else:
        customer_form = CustomerForm()
        order_form = SpecialOrderForm()

    return render(
        request,
        'bekapp/special_order_create.html',
        {
            'customer_form': customer_form,
            'order_form': order_form,
            'products': products,
        },
    )



def special_order_detail(request, special_order_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'CASHIER',
        'PRODUCTION_MANAGER'
    ]:
        return redirect('dashboard')

    special_order = get_object_or_404(
        SpecialOrder.objects.select_related(
            'customer',
            'created_by'
        ).prefetch_related(
            'items__product',
            'payments',
        ),
        id=special_order_id
    )

    def calculate_paid_amount(order):
        paid_payments = [
            payment
            for payment in order.payments.all()
            if payment.status == Payment.Status.PAID
        ]

        paid = sum(
            (payment.amount for payment in paid_payments),
            Decimal('0.00')
        )

        # Support older orders with a deposit but no deposit Payment record.
        deposit_recorded = any(
            (payment.notes or '').startswith(
                f"Deposit for special order {order.order_number}"
            )
            for payment in paid_payments
        )

        if order.deposit_amount > 0 and not deposit_recorded:
            paid += order.deposit_amount

        return paid

    paid_amount = calculate_paid_amount(special_order)

    remaining_amount = max(
        Decimal('0.00'),
        special_order.total_amount - paid_amount
    )

    payment_error = None

    if request.method == 'POST' and 'record_special_order_payment' in request.POST:
        if request.user.role not in ['OWNER', 'CASHIER']:
            return redirect('dashboard')

        if special_order.status != SpecialOrder.Status.READY:
            payment_error = 'Payment can only be collected for orders marked Ready.'

        elif remaining_amount <= 0:
            payment_error = 'This order has already been fully paid.'

        else:
            amount_text = request.POST.get('payment_amount', '').strip()
            method = request.POST.get('payment_method', '').strip()
            reference_number = request.POST.get(
                'reference_number', ''
            ).strip()

            try:
                amount = Decimal(amount_text)
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal('0.00')

            valid_methods = dict(Payment.Method.choices)

            if not amount.is_finite() or amount <= 0:
                payment_error = 'Enter a valid payment amount greater than zero.'

            elif amount > remaining_amount:
                payment_error = (
                    f'Payment cannot exceed the remaining balance of '
                    f'{remaining_amount:.2f} ETB.'
                )

            elif method not in valid_methods:
                payment_error = 'Please select a valid payment method.'

            else:
                with transaction.atomic():
                    locked_order = SpecialOrder.objects.select_for_update().get(
                        pk=special_order.pk
                    )

                    existing_paid_payments = list(
                        locked_order.payments.filter(
                            status=Payment.Status.PAID
                        )
                    )

                    current_paid = sum(
                        (p.amount for p in existing_paid_payments),
                        Decimal('0.00')
                    )

                    deposit_recorded = any(
                        (p.notes or '').startswith(
                            f"Deposit for special order "
                            f"{locked_order.order_number}"
                        )
                        for p in existing_paid_payments
                    )

                    if (
                        locked_order.deposit_amount > 0
                        and not deposit_recorded
                    ):
                        current_paid += locked_order.deposit_amount

                    current_balance = max(
                        Decimal('0.00'),
                        locked_order.total_amount - current_paid
                    )

                    if locked_order.status != SpecialOrder.Status.READY:
                        payment_error = (
                            'This order is no longer Ready for payment.'
                        )

                    elif current_balance <= 0:
                        payment_error = 'This order has already been fully paid.'

                    elif amount > current_balance:
                        payment_error = (
                            f'The remaining balance is now '
                            f'{current_balance:.2f} ETB. Please check the amount.'
                        )

                    else:
                        Payment.objects.create(
                            special_order=locked_order,
                            method=method,
                            amount=amount,
                            reference_number=reference_number,
                            status=Payment.Status.PAID,
                            notes=(
                                f"Payment for special order "
                                f"{locked_order.order_number}"
                            ),
                            recorded_by=request.user,
                        )

                if not payment_error:
                    return redirect(
                        'special_order_detail',
                        special_order_id=special_order.pk
                    )

    # Recalculate after processing a POST.
    special_order.refresh_from_db()
    paid_amount = calculate_paid_amount(special_order)

    remaining_amount = max(
        Decimal('0.00'),
        special_order.total_amount - paid_amount
    )

    return render(
        request,
        'bekapp/special_order_detail.html',
        {
            'special_order': special_order,
            'paid_amount': paid_amount,
            'remaining_amount': remaining_amount,
            'payments': special_order.payments.all(),
            'payment_methods': Payment.Method.choices,
            'payment_error': payment_error,
        }
    )


def recipe_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    recipes = Recipe.objects.select_related(
        'product'
    ).prefetch_related(
        'ingredients__ingredient'
    ).order_by(
        'product__name'
    )

    return render(
        request,
        'bekapp/recipe_list.html',
        {
            'recipes': recipes,
        }
    )

def recipe_create(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
    'OWNER',
    'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    if request.method == 'POST':

        recipe_form = RecipeForm(request.POST)

        if recipe_form.is_valid():

            ingredient_ids = request.POST.getlist('ingredient')
            quantities = request.POST.getlist('quantity')

            ingredient_data = []
            used_ingredients = set()

            for index, ingredient_id in enumerate(ingredient_ids):

                if not ingredient_id:
                    continue

                if index >= len(quantities):
                    continue

                quantity_value = quantities[index]

                if not quantity_value:
                    continue

                try:
                    quantity = Decimal(quantity_value)
                except (InvalidOperation, TypeError):
                    continue

                if quantity <= 0:
                    continue

                try:
                    ingredient = Ingredient.objects.get(
                        id=ingredient_id,
                        is_active=True
                    )
                except Ingredient.DoesNotExist:
                    continue

                # Prevent duplicate ingredients.
                if ingredient.id in used_ingredients:
                    continue

                used_ingredients.add(ingredient.id)

                ingredient_data.append({
                    'ingredient': ingredient,
                    'quantity': quantity,
                })

            if not ingredient_data:

                recipe_form.add_error(
                    None,
                    'Please add at least one ingredient to the recipe.'
                )

            else:

                with transaction.atomic():

                    recipe = recipe_form.save()

                    for item in ingredient_data:

                        RecipeIngredient.objects.create(
                            recipe=recipe,
                            ingredient=item['ingredient'],
                            quantity=item['quantity'],
                        )

                return redirect(
                    'recipe_detail',
                    recipe_id=recipe.id
                )

    else:

        recipe_form = RecipeForm()

    ingredient_form = RecipeIngredientForm()

    return render(
        request,
        'bekapp/recipe_create.html',
        {
            'recipe_form': recipe_form,
            'ingredient_form': ingredient_form,
        }
    )

def recipe_detail(request, recipe_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
    'OWNER',
    'PRODUCTION_MANAGER',
    ]:
     return redirect('dashboard')

    recipe = Recipe.objects.select_related(
        'product'
    ).prefetch_related(
        'ingredients__ingredient'
    ).get(id=recipe_id)

    return render(
        request,
        'bekapp/recipe_detail.html',
        {
            'recipe': recipe,
        }
    )

def recipe_edit(request, recipe_id):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
    'OWNER',
    'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    recipe = Recipe.objects.select_related(
        'product'
    ).prefetch_related(
        'ingredients__ingredient'
    ).get(id=recipe_id)

    if request.method == 'POST':

        recipe_form = RecipeForm(
            request.POST,
            instance=recipe
        )

        ingredient_ids = request.POST.getlist('ingredient')
        quantities = request.POST.getlist('quantity')

        ingredient_data = []
        used_ingredients = set()

        if recipe_form.is_valid():

            for index, ingredient_id in enumerate(ingredient_ids):

                if not ingredient_id:
                    continue

                if index >= len(quantities):
                    continue

                quantity_value = quantities[index]

                if not quantity_value:
                    continue

                try:
                    quantity = Decimal(quantity_value)

                except (InvalidOperation, TypeError):
                    continue

                if quantity <= 0:
                    continue

                try:
                    ingredient = Ingredient.objects.get(
                        id=ingredient_id,
                        is_active=True
                    )

                except Ingredient.DoesNotExist:
                    continue

                if ingredient.id in used_ingredients:
                    continue

                used_ingredients.add(ingredient.id)

                ingredient_data.append({
                    'ingredient': ingredient,
                    'quantity': quantity,
                })


            if not ingredient_data:

                recipe_form.add_error(
                    None,
                    'Please add at least one ingredient to the recipe.'
                )

            else:

                with transaction.atomic():

                    recipe_form.save()

                    recipe.ingredients.all().delete()

                    for item in ingredient_data:

                        RecipeIngredient.objects.create(
                            recipe=recipe,
                            ingredient=item['ingredient'],
                            quantity=item['quantity'],
                        )

                return redirect(
                    'recipe_detail',
                    recipe_id=recipe.id
                )

    else:

        recipe_form = RecipeForm(
            instance=recipe
        )

    ingredient_form = RecipeIngredientForm()

    return render(
        request,
        'bekapp/recipe_edit.html',
        {
            'recipe': recipe,
            'recipe_form': recipe_form,
            'ingredient_form': ingredient_form,
        }
    )

def ingredient_list(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    ingredients = Ingredient.objects.all().order_by('name')

    return render(
        request,
        'bekapp/ingredient_list.html',
        {
            'ingredients': ingredients,
        }
    )


def ingredient_create(request):

    if not request.user.is_authenticated:
        return redirect("login")

    if request.user.role != "OWNER":
        return redirect("dashboard")

    if request.method == "POST":
        form = IngredientForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect("ingredient_list")

    else:
        form = IngredientForm()

    return render(
        request,
        "bekapp/ingredient_form.html",
        {
            "form": form,
            "page_title": "Add Ingredient",
            "submit_text": "Save Ingredient",
        },
    )

def ingredient_edit(request, pk):

    if not request.user.is_authenticated:
        return redirect("login")

    if request.user.role != "OWNER":
        return redirect("dashboard")

    ingredient = get_object_or_404(Ingredient, pk=pk)

    if request.method == "POST":
        form = IngredientForm(
            request.POST,
            instance=ingredient,
        )

        if form.is_valid():
            form.save()
            return redirect("ingredient_list")

    else:
        form = IngredientForm(instance=ingredient)

    return render(
        request,
        "bekapp/ingredient_form.html",
        {
            "form": form,
            "page_title": "Edit Ingredient",
            "submit_text": "Update Ingredient",
        },
    )

def stock_movement_create(request):

    if not request.user.is_authenticated:
        return redirect("login")

    if request.user.role != "OWNER":
        return redirect("dashboard")

    if request.method == "POST":

        form = StockMovementForm(request.POST)

        if form.is_valid():

            movement_type = form.cleaned_data["movement_type"]
            quantity = form.cleaned_data["quantity"]

            with transaction.atomic():

                ingredient = (
                    Ingredient.objects
                    .select_for_update()
                    .get(
                        pk=form.cleaned_data["ingredient"].pk
                    )
                )

                if movement_type == StockMovement.MovementType.RECEIVED:

                    ingredient.current_stock += quantity

                elif movement_type == StockMovement.MovementType.USED:

                    if quantity > ingredient.current_stock:

                        form.add_error(
                            "quantity",
                            (
                                f"Insufficient stock. "
                                f"Current stock is "
                                f"{ingredient.current_stock} "
                                f"{ingredient.get_unit_display()}."
                            ),
                        )

                        return render(
                            request,
                            "bekapp/stock_movement_form.html",
                            {
                                "form": form,
                                "page_title": "Record Stock Movement",
                            },
                        )

                    ingredient.current_stock -= quantity

                elif movement_type == StockMovement.MovementType.ADJUSTMENT:

                    ingredient.current_stock = quantity

                movement = form.save(commit=False)

                movement.created_by = request.user
                movement.ingredient = ingredient

                movement.save()

                ingredient.save(
                    update_fields=[
                        "current_stock",
                        "updated_at",
                    ]
                )

            return redirect("ingredient_list")

    else:

        form = StockMovementForm()

    return render(
        request,
        "bekapp/stock_movement_form.html",
        {
            "form": form,
            "page_title": "Record Stock Movement",
        },
    )

def stock_movement_list(request):

    if not request.user.is_authenticated:
        return redirect("login")

    if request.user.role != "OWNER":
        return redirect("dashboard")

    movements = (
        StockMovement.objects
        .select_related("ingredient", "created_by")
        .all()
    )

    return render(
        request,
        "bekapp/stock_movement_list.html",
        {
            "movements": movements,
        },
    )

def recipe_product_ingredients(request, product_id):

    if not request.user.is_authenticated:
        return JsonResponse(
            {'error': 'Authentication required.'},
            status=403
        )

    if request.user.role != 'OWNER':
        return JsonResponse(
            {'error': 'Permission denied.'},
            status=403
        )

    try:
        recipe = Recipe.objects.prefetch_related(
            'ingredients__ingredient'
        ).get(
            product_id=product_id
        )

    except Recipe.DoesNotExist:

        return JsonResponse({
            'recipe_exists': False,
            'ingredients': [],
        })

    ingredients = []

    for item in recipe.ingredients.all():

        ingredients.append({
            'ingredient_id': item.ingredient.id,
            'ingredient_name': item.ingredient.name,
            'quantity': str(item.quantity),
            'unit': item.ingredient.unit,
        })

    return JsonResponse({
        'recipe_exists': True,
        'ingredients': ingredients,
    })

def user_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    users = User.objects.all().order_by(
        'role',
        'username'
    )

    return render(
        request,
        'bekapp/user_list.html',
        {
            'users': users,
        }
    )

def staff_create(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    if request.method == 'POST':
        form = StaffCreateForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect('user_list')

    else:
        form = StaffCreateForm()

    return render(
        request,
        'bekapp/staff_form.html',
        {
            'form': form,
        }
    )

def staff_edit(request, user_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    user = User.objects.get(id=user_id)

    # Owner accounts cannot be edited through staff management.
    if user.role == 'OWNER':
        return redirect('user_list')

    if request.method == 'POST':
        form = StaffEditForm(
            request.POST,
            instance=user
        )

        if form.is_valid():
            form.save()
            return redirect('user_list')

    else:
        form = StaffEditForm(
            instance=user
        )

    return render(
        request,
        'bekapp/staff_form.html',
        {
            'form': form,
            'editing': True,
            'staff_user': user,
        }
    )

def product_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'PRODUCTION_MANAGER',
        'CASHIER',
    ]:
        return redirect('dashboard')

    products = Product.objects.select_related(
        'category',
    ).all().order_by(
        'category__name',
        'name'
    )

    return render(
        request,
        'bekapp/product_list.html',
        {
            'products': products,
        }
    )
def product_create(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    if request.method == 'POST':
        form = ProductForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect('product_list')

    else:
        form = ProductForm()

    return render(
        request,
        'bekapp/product_form.html',
        {
            'form': form,
        }
    )

def product_edit(request, product_id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    product = Product.objects.get(id=product_id)

    if request.method == 'POST':
        form = ProductForm(
            request.POST,
            instance=product
        )

        if form.is_valid():
            form.save()
            return redirect('product_list')

    else:
        form = ProductForm(
            instance=product
        )

    return render(
        request,
        'bekapp/product_form.html',
        {
            'form': form,
            'editing': True,
            'product': product,
        }
    )

def product_toggle_status(request, product_id):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role not in [
        'OWNER',
        'PRODUCTION_MANAGER',
    ]:
        return redirect('dashboard')

    product = Product.objects.get(id=product_id)

    product.is_available = not product.is_available

    product.save(
        update_fields=['is_available']
    )

    return redirect('product_list')

def product_delete(request, product_id):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    product = Product.objects.get(id=product_id)

    if request.method == 'POST':

        try:

            product.delete()

        except ProtectedError:

            return render(
                request,
                'bekapp/product_delete.html',
                {
                    'product': product,
                    'delete_error': (
                        'This product cannot be deleted because it is '
                        'connected to existing sales, production records, '
                        'or special orders. Deactivate the product instead.'
                    ),
                }
            )

        return redirect('product_list')

    return render(
        request,
        'bekapp/product_delete.html',
        {
            'product': product,
        }
    )

def owner_reports(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    context = {
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(
        request,
        'bekapp/owner_reports.html',
        context
    )

def owner_sales_report(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    ).select_related(
        'cashier'
    ).prefetch_related(
        'items__product',
        'payments'
    )

    total_sales = 0
    total_discount = 0
    total_paid = 0
    total_outstanding = 0

    for sale in sales:

        paid_amount = sum(
            payment.amount
            for payment in sale.payments.all()
            if payment.status == Payment.Status.PAID
        )

        outstanding = sale.total_amount - paid_amount

        total_sales += sale.total_amount
        total_discount += sale.discount
        total_paid += paid_amount
        total_outstanding += outstanding

        sale.report_paid_amount = paid_amount
        sale.report_outstanding = outstanding

    context = {
        'start_date': start_date,
        'end_date': end_date,

        'sales': sales,

        'sales_count': sales.count(),
        'total_sales': total_sales,
        'total_discount': total_discount,
        'total_paid': total_paid,
        'total_outstanding': total_outstanding,

        'business_settings': BusinessSettings.objects.first(),
    }

    return render(
        request,
        'bekapp/owner_sales_report.html',
        context
    )



def owner_sales_report_csv(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    ).select_related(
        'cashier'
    ).prefetch_related(
        'items__product',
        'payments'
    )

    # ---------------------------------------------------------
    # BUSINESS SETTINGS
    # ---------------------------------------------------------

    business_settings = BusinessSettings.objects.first()

    # ---------------------------------------------------------
    # CSV RESPONSE
    # ---------------------------------------------------------

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="sales_report_'
        f'{start_date}_to_{end_date}.csv"'
    )

    writer = csv.writer(response)

    # ---------------------------------------------------------
    # BUSINESS INFORMATION
    # ---------------------------------------------------------

    if business_settings:

        writer.writerow([
            'Business Name',
            business_settings.business_name,
        ])

        writer.writerow([
            'Phone',
            business_settings.phone,
        ])

        writer.writerow([
            'Email',
            business_settings.email,
        ])

        writer.writerow([
            'Address',
            business_settings.address,
        ])

    else:

        writer.writerow([
            'Business Name',
            'Bakery Management',
        ])

    writer.writerow([])

    # ---------------------------------------------------------
    # REPORT INFORMATION
    # ---------------------------------------------------------

    writer.writerow([
        'Sales Report',
    ])

    writer.writerow([
        'Report Period',
        f'{start_date} to {end_date}',
    ])

    writer.writerow([])

    # ---------------------------------------------------------
    # SALES TABLE HEADER
    # ---------------------------------------------------------

    writer.writerow([
        'Sale Number',
        'Date',
        'Cashier',
        'Products',
        'Quantity',
        'Discount',
        'Sale Total',
        'Amount Paid',
        'Remaining',
        'Payment Status',
    ])

    # ---------------------------------------------------------
    # SALES DATA
    # ---------------------------------------------------------

    for sale in sales:

        paid_amount = sum(
            payment.amount
            for payment in sale.payments.all()
            if payment.status == Payment.Status.PAID
        )

        outstanding = (
            sale.total_amount - paid_amount
        )

        products = ', '.join(
            item.product.name
            for item in sale.items.all()
        )

        quantities = ', '.join(
            str(item.quantity)
            for item in sale.items.all()
        )

        writer.writerow([
            sale.sale_number,
            sale.sale_date.strftime(
                '%d %b %Y %H:%M'
            ),
            sale.cashier.username,
            products,
            quantities,
            sale.discount,
            sale.total_amount,
            paid_amount,
            outstanding,
            sale.get_payment_status_display(),
        ])

    return response




def owner_sales_report_excel(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    ).select_related(
        'cashier'
    ).prefetch_related(
        'items__product',
        'payments'
    )

    # ---------------------------------------------------------
    # BUSINESS SETTINGS
    # ---------------------------------------------------------

    business_settings = BusinessSettings.objects.first()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Sales Report'

    # ---------------------------------------------------------
    # BUSINESS INFORMATION
    # ---------------------------------------------------------

    if business_settings:

        worksheet['A1'] = business_settings.business_name
        worksheet['A1'].font = Font(
            bold=True,
            size=16,
        )

        worksheet['A2'] = 'Phone'
        worksheet['B2'] = business_settings.phone

        worksheet['A3'] = 'Email'
        worksheet['B3'] = business_settings.email

        worksheet['A4'] = 'Address'
        worksheet['B4'] = business_settings.address

        worksheet['A6'] = 'SALES REPORT'
        worksheet['A6'].font = Font(
            bold=True,
            size=14,
        )

        worksheet['A7'] = 'Report Period'
        worksheet['B7'] = f'{start_date} to {end_date}'

        # -----------------------------------------------------
        # BUSINESS LOGO
        # -----------------------------------------------------

        if business_settings.logo:
            try:
                logo_path = business_settings.logo.path

                logo = ExcelImage(logo_path)

                logo.width = 140
                logo.height = 70

                worksheet.add_image(
                    logo,
                    'D1',
                )

            except Exception:
                pass

    else:

        worksheet['A1'] = 'Bakery Management'
        worksheet['A1'].font = Font(
            bold=True,
            size=16,
        )

        worksheet['A3'] = 'SALES REPORT'
        worksheet['A3'].font = Font(
            bold=True,
            size=14,
        )

        worksheet['A4'] = 'Report Period'
        worksheet['B4'] = f'{start_date} to {end_date}'

    # ---------------------------------------------------------
    # REPORT TABLE
    # ---------------------------------------------------------

    table_start_row = 9 if business_settings else 6

    headers = [
        'Sale Number',
        'Date',
        'Cashier',
        'Products',
        'Quantity',
        'Discount',
        'Sale Total',
        'Amount Paid',
        'Remaining',
        'Payment Status',
    ]

    worksheet.append([])

    for _ in range(
        table_start_row - worksheet.max_row - 1
    ):
        worksheet.append([])

    worksheet.append(headers)

    header_row = worksheet.max_row

    # ---------------------------------------------------------
    # HEADER STYLING
    # ---------------------------------------------------------

    header_fill = PatternFill(
        fill_type='solid',
        fgColor='159A96',
    )

    header_font = Font(
        bold=True,
        color='FFFFFF',
    )

    thin_border = Border(
        bottom=Side(
            style='thin',
            color='CCCCCC',
        )
    )

    for cell in worksheet[header_row]:

        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal='center',
            vertical='center',
        )
        cell.border = thin_border

    # ---------------------------------------------------------
    # SALES DATA
    # ---------------------------------------------------------

    for sale in sales:

        paid_amount = sum(
            payment.amount
            for payment in sale.payments.all()
            if payment.status == Payment.Status.PAID
        )

        outstanding = sale.total_amount - paid_amount

        products = ', '.join(
            item.product.name
            for item in sale.items.all()
        )

        quantities = ', '.join(
            str(item.quantity)
            for item in sale.items.all()
        )

        worksheet.append([
            sale.sale_number,
            sale.sale_date.strftime(
                '%d %b %Y %H:%M'
            ),
            sale.cashier.username,
            products,
            quantities,
            float(sale.discount),
            float(sale.total_amount),
            float(paid_amount),
            float(outstanding),
            sale.get_payment_status_display(),
        ])

    # ---------------------------------------------------------
    # FORMAT COLUMNS
    # ---------------------------------------------------------

    column_widths = {
        'A': 16,
        'B': 20,
        'C': 16,
        'D': 35,
        'E': 15,
        'F': 14,
        'G': 15,
        'H': 15,
        'I': 15,
        'J': 20,
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[column].width = width

    # ---------------------------------------------------------
    # FREEZE HEADER
    # ---------------------------------------------------------

    worksheet.freeze_panes = f'A{header_row + 1}'

    # ---------------------------------------------------------
    # RESPONSE
    # ---------------------------------------------------------

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        f'attachment; filename="sales_report_'
        f'{start_date}_to_{end_date}.xlsx"'
    )

    workbook.save(response)

    return response



def owner_sales_report_pdf(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    business_settings = BusinessSettings.objects.first()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    ).select_related(
        'cashier'
    ).prefetch_related(
        'items__product',
        'payments'
    )

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="sales_report_'
        f'{start_date}_to_{end_date}.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()

    story = []

    title = styles['Title']
    title.textColor = colors.HexColor('#17324d')
    title.fontSize = 20

    normal = styles['Normal']
    normal.fontSize = 9

    # ---------------------------------------------------------
    # BUSINESS HEADER
    # ---------------------------------------------------------

    if business_settings and business_settings.logo:
        logo = Image(
            business_settings.logo.path,
            width=30 * mm,
            height=30 * mm,
        )

        logo.hAlign = 'CENTER'

        story.append(logo)

        story.append(
            Spacer(1, 3 * mm)
        )

    if business_settings:
        business_name = business_settings.business_name
        phone = business_settings.phone
        email = business_settings.email
        address = business_settings.address
    else:
        business_name = 'Bakery Management'
        phone = ''
        email = ''
        address = ''

    story.append(
        Paragraph(
            business_name,
            title
        )
    )

    if phone:
        story.append(
            Paragraph(
                f'Phone: {phone}',
                normal
            )
        )

    if email:
        story.append(
            Paragraph(
                f'Email: {email}',
                normal
            )
        )

    if address:
        story.append(
            Paragraph(
                f'Address: {address}',
                normal
            )
        )

    story.append(
        Spacer(1, 4 * mm)
    )

    story.append(
        Paragraph(
            'SALES REPORT',
            styles['Heading2']
        )
    )

    story.append(
        Spacer(1, 2 * mm)
    )

    story.append(
        Paragraph(
            f'Report Period: {start_date} to {end_date}',
            normal
        )
    )

    story.append(
        Spacer(1, 5 * mm)
    )

    # ---------------------------------------------------------
    # SALES TOTALS
    # ---------------------------------------------------------

    total_sales = 0
    total_discount = 0
    total_paid = 0
    total_outstanding = 0

    table_data = [
        [
            'Sale Number',
            'Date',
            'Cashier',
            'Products',
            'Quantity',
            'Discount',
            'Sale Total',
            'Paid',
            'Remaining',
            'Status',
        ]
    ]

    for sale in sales:

        paid_amount = sum(
            payment.amount
            for payment in sale.payments.all()
            if payment.status == Payment.Status.PAID
        )

        outstanding = sale.total_amount - paid_amount

        total_sales += sale.total_amount
        total_discount += sale.discount
        total_paid += paid_amount
        total_outstanding += outstanding

        products = ', '.join(
            item.product.name
            for item in sale.items.all()
        )

        quantities = ', '.join(
            str(item.quantity)
            for item in sale.items.all()
        )

        table_data.append([
            sale.sale_number,
            sale.sale_date.strftime('%d %b %Y %H:%M'),
            sale.cashier.username,
            products,
            quantities,
            f'{sale.discount:.2f}',
            f'{sale.total_amount:.2f}',
            f'{paid_amount:.2f}',
            f'{outstanding:.2f}',
            sale.get_payment_status_display(),
        ])

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    summary_data = [
        ['Number of Sales', str(sales.count())],
        ['Total Sales', f'{total_sales:.2f} ETB'],
        ['Total Discount', f'{total_discount:.2f} ETB'],
        ['Total Paid', f'{total_paid:.2f} ETB'],
        ['Outstanding', f'{total_outstanding:.2f} ETB'],
    ]

    summary_table = Table(
        summary_data,
        colWidths=[45 * mm, 45 * mm]
    )

    summary_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (0, -1),
                colors.HexColor('#f8fafb')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, -1),
                colors.HexColor('#17324d')
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, -1),
                'Helvetica'
            ),
            (
                'FONTNAME',
                (0, 0),
                (0, -1),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor('#e5e9ed')
            ),
            (
                'PADDING',
                (0, 0),
                (-1, -1),
                6
            ),
        ])
    )

    story.append(summary_table)

    story.append(
        Spacer(1, 7 * mm)
    )

    # ---------------------------------------------------------
    # SALES TRANSACTIONS TABLE
    # ---------------------------------------------------------

    sales_table = Table(
        table_data,
        repeatRows=1,
        colWidths=[
            30 * mm,
            32 * mm,
            25 * mm,
            55 * mm,
            20 * mm,
            25 * mm,
            27 * mm,
            27 * mm,
            27 * mm,
            30 * mm,
        ],
    )

    sales_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'FONTSIZE',
                (0, 0),
                (-1, -1),
                7
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor('#d9dee3')
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
            (
                'ROWBACKGROUNDS',
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor('#f8fafb')
                ]
            ),
            (
                'PADDING',
                (0, 0),
                (-1, -1),
                5
            ),
        ])
    )

    story.append(
        Paragraph(
            'Sales Transactions',
            styles['Heading2']
        )
    )

    story.append(
        Spacer(1, 3 * mm)
    )

    story.append(sales_table)

    document.build(story)

    return response


    story.append(
        Paragraph(
            'Sales Transactions',
            styles['Heading2']
        )
    )

    story.append(
        Spacer(1, 3 * mm)
    )

    story.append(sales_table)

    document.build(story)

    return response


def owner_payment_report(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    ).select_related(
        'sale',
        'recorded_by'
    )

    total_paid = 0
    total_pending = 0
    total_failed = 0
    total_refunded = 0

    paid_count = 0
    pending_count = 0
    failed_count = 0
    refunded_count = 0

    for payment in payments:

        if payment.status == Payment.Status.PAID:
            total_paid += payment.amount
            paid_count += 1

        elif payment.status == Payment.Status.PENDING:
            total_pending += payment.amount
            pending_count += 1

        elif payment.status == Payment.Status.FAILED:
            total_failed += payment.amount
            failed_count += 1

        elif payment.status == Payment.Status.REFUNDED:
            total_refunded += payment.amount
            refunded_count += 1

    context = {
        'business_settings': business_settings,

        'start_date': start_date,
        'end_date': end_date,
        'payments': payments,
        'payments_count': payments.count(),

        'total_paid': total_paid,
        'total_pending': total_pending,
        'total_failed': total_failed,
        'total_refunded': total_refunded,

        'paid_count': paid_count,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'refunded_count': refunded_count,
    }

    return render(
        request,
        'bekapp/owner_payment_report.html',
        context
    )


def owner_payment_report_csv(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    ).select_related(
        'sale',
        'recorded_by'
    )

    business_settings = BusinessSettings.objects.first()

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="payment_report_'
        f'{start_date}_to_{end_date}.csv"'
    )

    writer = csv.writer(response)

    # BUSINESS INFORMATION
    if business_settings:
        writer.writerow([
            'Business Name',
            business_settings.business_name
        ])
        writer.writerow([
            'Phone',
            business_settings.phone
        ])
        writer.writerow([
            'Email',
            business_settings.email
        ])
        writer.writerow([
            'Address',
            business_settings.address
        ])
    else:
        writer.writerow([
            'Business Name',
            'Bakery Management'
        ])

    writer.writerow([])

    # REPORT INFORMATION
    writer.writerow([
        'Payment Report'
    ])

    writer.writerow([
        'Report Period',
        f'{start_date} to {end_date}'
    ])

    writer.writerow([])

    # TABLE HEADERS
    writer.writerow([
        'Sale Number',
        'Date',
        'Payment Method',
        'Amount',
        'Status',
        'Reference',
        'Recorded By',
    ])

    # PAYMENT DATA
    for payment in payments:

        writer.writerow([
            payment.sale.sale_number,
            payment.payment_date.strftime(
                '%d %b %Y %H:%M'
            ),
            payment.get_method_display(),
            payment.amount,
            payment.get_status_display(),
            payment.reference_number or '',
            payment.recorded_by.username,
        ])

    return response




def owner_payment_report_excel(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    ).select_related(
        'sale',
        'recorded_by'
    )

    business_settings = BusinessSettings.objects.first()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Payment Report'

    # -------------------------------------------------
    # BUSINESS INFORMATION
    # -------------------------------------------------

    current_row = 1

    if business_settings:

        worksheet.cell(
            row=current_row,
            column=1,
            value=business_settings.business_name
        )

        worksheet.cell(
            row=current_row,
            column=1
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

        if business_settings.phone:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Phone: {business_settings.phone}'
            )
            current_row += 1

        if business_settings.email:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Email: {business_settings.email}'
            )
            current_row += 1

        if business_settings.address:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Address: {business_settings.address}'
            )
            current_row += 1

        # BUSINESS LOGO
        if business_settings.logo:
            try:
                logo = ExcelImage(
                    business_settings.logo.path
                )

                logo.width = 120
                logo.height = 70

                worksheet.add_image(
                    logo,
                    'F1'
                )

            except Exception:
                pass

    else:
        worksheet.cell(
            row=current_row,
            column=1,
            value='Bakery Management'
        )

        worksheet.cell(
            row=current_row,
            column=1
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

    # -------------------------------------------------
    # REPORT TITLE
    # -------------------------------------------------

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Payment Report'
    )

    worksheet.cell(
        row=current_row,
        column=1
    ).font = Font(
        bold=True,
        size=14
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Report Period'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=f'{start_date} to {end_date}'
    )

    current_row += 2

    # -------------------------------------------------
    # TABLE HEADERS
    # -------------------------------------------------

    headers = [
        'Sale Number',
        'Date',
        'Payment Method',
        'Amount',
        'Status',
        'Reference',
        'Recorded By',
    ]

    for column_number, header in enumerate(
        headers,
        start=1
    ):

        cell = worksheet.cell(
            row=current_row,
            column=column_number,
            value=header
        )

        cell.font = Font(
            bold=True
        )

        cell.alignment = Alignment(
            horizontal='center',
            vertical='center'
        )

        cell.fill = PatternFill(
            fill_type='solid',
            fgColor='159A96'
        )

        cell.border = Border(
            bottom=Side(
                style='thin'
            )
        )

    # -------------------------------------------------
    # PAYMENT DATA
    # -------------------------------------------------

    data_start_row = current_row + 1

    for payment in payments:

        current_row += 1

        worksheet.append([
            payment.sale.sale_number,
            payment.payment_date.strftime(
                '%d %b %Y %H:%M'
            ),
            payment.get_method_display(),
            float(payment.amount),
            payment.get_status_display(),
            payment.reference_number or '',
            payment.recorded_by.username,
        ])

    # -------------------------------------------------
    # FORMATTING
    # -------------------------------------------------

    worksheet.freeze_panes = f'A{data_start_row}'

    column_widths = {
        'A': 18,
        'B': 22,
        'C': 20,
        'D': 15,
        'E': 15,
        'F': 25,
        'G': 20,
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[
            column
        ].width = width

    # Amount formatting
    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row,
        min_col=4,
        max_col=4
    ):
        row[0].number_format = '#,##0.00'

    # Alignment
    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row
    ):
        for cell in row:
            cell.alignment = Alignment(
                vertical='center'
            )

    # -------------------------------------------------
    # RESPONSE
    # -------------------------------------------------

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        f'attachment; filename="payment_report_'
        f'{start_date}_to_{end_date}.xlsx"'
    )

    workbook.save(response)

    return response




def owner_payment_report_pdf(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    ).select_related(
        'sale',
        'recorded_by'
    )

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="payment_report_'
        f'{start_date}_to_{end_date}.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()

    story = []

    title = styles['Title']
    title.textColor = colors.HexColor('#17324d')
    title.fontSize = 20

    business_name_style = ParagraphStyle(
        'BusinessName',
        parent=styles['Title'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceAfter=4,
    )

    business_info_style = ParagraphStyle(
        'BusinessInfo',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#6c757d'),
        alignment=1,
    )

    report_title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading2'],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceBefore=8,
        spaceAfter=5,
    )

    normal = styles['Normal']
    normal.fontSize = 9

    # =========================================================
    # BUSINESS INFORMATION
    # =========================================================

    if business_settings:

        if business_settings.logo:

            try:

                logo = Image(
                    business_settings.logo.path,
                    width=28 * mm,
                    height=23 * mm,
                )

                logo.hAlign = 'CENTER'

                story.append(logo)

                story.append(
                    Spacer(1, 3 * mm)
                )

            except Exception:
                pass

        story.append(
            Paragraph(
                business_settings.business_name,
                business_name_style
            )
        )

        business_info = []

        if business_settings.phone:
            business_info.append(
                f'Phone: {business_settings.phone}'
            )

        if business_settings.email:
            business_info.append(
                f'Email: {business_settings.email}'
            )

        if business_settings.address:
            business_info.append(
                f'Address: {business_settings.address}'
            )

        if business_info:

            story.append(
                Paragraph(
                    '<br/>'.join(business_info),
                    business_info_style
                )
            )

    # =========================================================
    # REPORT TITLE
    # =========================================================

    story.append(
        Paragraph(
            'Payment Report',
            report_title_style
        )
    )

    story.append(
        Paragraph(
            f'Report Period: {start_date} to {end_date}',
            normal
        )
    )

    story.append(
        Spacer(1, 5 * mm)
    )

    # =========================================================
    # PAYMENT TOTALS
    # =========================================================

    total_paid = 0
    total_pending = 0
    total_failed = 0
    total_refunded = 0

    paid_count = 0
    pending_count = 0
    failed_count = 0
    refunded_count = 0

    for payment in payments:

        if payment.status == Payment.Status.PAID:
            total_paid += payment.amount
            paid_count += 1

        elif payment.status == Payment.Status.PENDING:
            total_pending += payment.amount
            pending_count += 1

        elif payment.status == Payment.Status.FAILED:
            total_failed += payment.amount
            failed_count += 1

        elif payment.status == Payment.Status.REFUNDED:
            total_refunded += payment.amount
            refunded_count += 1

    # =========================================================
    # SUMMARY
    # =========================================================

    summary_data = [
        [
            'Number of Payments',
            str(payments.count())
        ],
        [
            'Paid',
            f'{total_paid:.2f} ETB'
        ],
        [
            'Pending',
            f'{total_pending:.2f} ETB'
        ],
        [
            'Failed',
            f'{total_failed:.2f} ETB'
        ],
        [
            'Refunded',
            f'{total_refunded:.2f} ETB'
        ],
    ]

    summary_table = Table(
        summary_data,
        colWidths=[45 * mm, 45 * mm]
    )

    summary_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (0, -1),
                colors.HexColor('#f8fafb')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, -1),
                colors.HexColor('#17324d')
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, -1),
                'Helvetica'
            ),
            (
                'FONTNAME',
                (0, 0),
                (0, -1),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor('#e5e9ed')
            ),
            (
                'PADDING',
                (0, 0),
                (-1, -1),
                6
            ),
        ])
    )

    story.append(summary_table)

    story.append(
        Spacer(1, 7 * mm)
    )

    # =========================================================
    # PAYMENT TRANSACTIONS
    # =========================================================

    story.append(
        Paragraph(
            'Payment Transactions',
            styles['Heading2']
        )
    )

    story.append(
        Spacer(1, 3 * mm)
    )

    table_data = [
        [
            'Sale Number',
            'Date',
            'Payment Method',
            'Amount',
            'Status',
            'Reference',
            'Recorded By',
        ]
    ]

    for payment in payments:

        table_data.append([
            payment.sale.sale_number,
            payment.payment_date.strftime(
                '%d %b %Y %H:%M'
            ),
            payment.get_method_display(),
            f'{payment.amount:.2f}',
            payment.get_status_display(),
            payment.reference_number or '—',
            payment.recorded_by.username,
        ])

    payment_table = Table(
        table_data,
        repeatRows=1,
        colWidths=[
            35 * mm,
            35 * mm,
            35 * mm,
            30 * mm,
            30 * mm,
            45 * mm,
            35 * mm,
        ],
    )

    payment_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'FONTSIZE',
                (0, 0),
                (-1, -1),
                8
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor('#d9dee3')
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
            (
                'ROWBACKGROUNDS',
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor('#f8fafb')
                ]
            ),
            (
                'PADDING',
                (0, 0),
                (-1, -1),
                5
            ),
        ])
    )

    story.append(payment_table)

    document.build(story)

    return response

def owner_production_report(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    ).select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    planned_quantity = 0
    actual_quantity = 0

    completed_count = 0
    in_progress_count = 0
    planned_count = 0
    cancelled_count = 0

    for production in productions:

        if production.status == Production.Status.COMPLETED:
            completed_count += 1

        elif production.status == Production.Status.IN_PROGRESS:
            in_progress_count += 1

        elif production.status == Production.Status.PLANNED:
            planned_count += 1

        elif production.status == Production.Status.CANCELLED:
            cancelled_count += 1

        for item in production.items.all():

            planned_quantity += item.planned_quantity
            actual_quantity += item.actual_quantity

    context = {
        'business_settings': business_settings,

        'start_date': start_date,
        'end_date': end_date,

        'productions': productions,
        'productions_count': productions.count(),

        'planned_quantity': planned_quantity,
        'actual_quantity': actual_quantity,

        'completed_count': completed_count,
        'in_progress_count': in_progress_count,
        'planned_count': planned_count,
        'cancelled_count': cancelled_count,
    }

    return render(
        request,
        'bekapp/owner_production_report.html',
        context
    )


def owner_production_report_csv(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    ).select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    business_settings = BusinessSettings.objects.first()

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="production_report_'
        f'{start_date}_to_{end_date}.csv"'
    )

    writer = csv.writer(response)

    # BUSINESS INFORMATION
    if business_settings:
        writer.writerow([
            'Business Name',
            business_settings.business_name
        ])
        writer.writerow([
            'Phone',
            business_settings.phone
        ])
        writer.writerow([
            'Email',
            business_settings.email
        ])
        writer.writerow([
            'Address',
            business_settings.address
        ])
    else:
        writer.writerow([
            'Business Name',
            'Bakery Management'
        ])

    writer.writerow([])

    # REPORT INFORMATION
    writer.writerow([
        'Production Report'
    ])

    writer.writerow([
        'Report Period',
        f'{start_date} to {end_date}'
    ])

    writer.writerow([])

    # TABLE HEADERS
    writer.writerow([
        'Production Date',
        'Created By',
        'Products',
        'Planned Quantity',
        'Actual Quantity',
        'Status',
    ])

    # PRODUCTION DATA
    for production in productions:

        products = ', '.join(
            item.product.name
            for item in production.items.all()
        )

        planned_quantities = ', '.join(
            str(item.planned_quantity)
            for item in production.items.all()
        )

        actual_quantities = ', '.join(
            str(item.actual_quantity)
            for item in production.items.all()
        )

        writer.writerow([
            production.production_date.strftime(
                '%d %b %Y'
            ),
            production.created_by.username,
            products,
            planned_quantities,
            actual_quantities,
            production.get_status_display(),
        ])

    return response



def owner_production_report_excel(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    ).select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    business_settings = BusinessSettings.objects.first()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Production Report'

    # -------------------------------------------------
    # BUSINESS INFORMATION
    # -------------------------------------------------

    current_row = 1

    if business_settings:

        worksheet.cell(
            row=current_row,
            column=1,
            value=business_settings.business_name
        )

        worksheet.cell(
            row=current_row,
            column=1
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

        if business_settings.phone:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Phone: {business_settings.phone}'
            )
            current_row += 1

        if business_settings.email:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Email: {business_settings.email}'
            )
            current_row += 1

        if business_settings.address:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Address: {business_settings.address}'
            )
            current_row += 1

        # BUSINESS LOGO
        if business_settings.logo:
            try:
                logo = ExcelImage(
                    business_settings.logo.path
                )

                logo.width = 120
                logo.height = 70

                worksheet.add_image(
                    logo,
                    'G1'
                )

            except Exception:
                pass

    else:
        worksheet.cell(
            row=current_row,
            column=1,
            value='Bakery Management'
        )

        worksheet.cell(
            row=current_row,
            column=1
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

    # -------------------------------------------------
    # REPORT TITLE
    # -------------------------------------------------

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Production Report'
    )

    worksheet.cell(
        row=current_row,
        column=1
    ).font = Font(
        bold=True,
        size=14
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Report Period'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=f'{start_date} to {end_date}'
    )

    current_row += 2

    # -------------------------------------------------
    # TABLE HEADERS
    # -------------------------------------------------

    headers = [
        'Production Date',
        'Created By',
        'Products',
        'Planned Quantity',
        'Actual Quantity',
        'Status',
    ]

    for column_number, header in enumerate(
        headers,
        start=1
    ):

        cell = worksheet.cell(
            row=current_row,
            column=column_number,
            value=header
        )

        cell.font = Font(
            bold=True
        )

        cell.alignment = Alignment(
            horizontal='center',
            vertical='center'
        )

        cell.fill = PatternFill(
            fill_type='solid',
            fgColor='159A96'
        )

        cell.border = Border(
            bottom=Side(
                style='thin'
            )
        )

    # -------------------------------------------------
    # PRODUCTION DATA
    # -------------------------------------------------

    data_start_row = current_row + 1

    for production in productions:

        products = ', '.join(
            item.product.name
            for item in production.items.all()
        )

        planned_quantities = ', '.join(
            str(item.planned_quantity)
            for item in production.items.all()
        )

        actual_quantities = ', '.join(
            str(item.actual_quantity)
            for item in production.items.all()
        )

        worksheet.cell(
            row=current_row + 1,
            column=1,
            value=production.production_date.strftime(
                '%d %b %Y'
            )
        )

        worksheet.cell(
            row=current_row + 1,
            column=2,
            value=production.created_by.username
        )

        worksheet.cell(
            row=current_row + 1,
            column=3,
            value=products
        )

        worksheet.cell(
            row=current_row + 1,
            column=4,
            value=planned_quantities
        )

        worksheet.cell(
            row=current_row + 1,
            column=5,
            value=actual_quantities
        )

        worksheet.cell(
            row=current_row + 1,
            column=6,
            value=production.get_status_display()
        )

        current_row += 1

    # -------------------------------------------------
    # FORMATTING
    # -------------------------------------------------

    worksheet.freeze_panes = f'A{data_start_row}'

    column_widths = {
        'A': 20,
        'B': 20,
        'C': 35,
        'D': 22,
        'E': 22,
        'F': 18,
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[
            column
        ].width = width

    # Alignment
    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row
    ):
        for cell in row:
            cell.alignment = Alignment(
                vertical='center',
                wrap_text=True
            )

    # -------------------------------------------------
    # RESPONSE
    # -------------------------------------------------

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        f'attachment; filename="production_report_'
        f'{start_date}_to_{end_date}.xlsx"'
    )

    workbook.save(response)

    return response




def owner_production_report_pdf(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    ).select_related(
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="production_report_'
        f'{start_date}_to_{end_date}.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()

    story = []

    business_name_style = ParagraphStyle(
        'ProductionBusinessName',
        parent=styles['Title'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceAfter=4,
    )

    business_info_style = ParagraphStyle(
        'ProductionBusinessInfo',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#6c757d'),
        alignment=1,
    )

    report_title_style = ParagraphStyle(
        'ProductionReportTitle',
        parent=styles['Heading2'],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceBefore=8,
        spaceAfter=5,
    )

    normal = styles['Normal']
    normal.fontSize = 9

    # =========================================================
    # BUSINESS INFORMATION
    # =========================================================

    if business_settings:

        if business_settings.logo:

            try:

                logo = Image(
                    business_settings.logo.path,
                    width=28 * mm,
                    height=23 * mm,
                )

                logo.hAlign = 'CENTER'

                story.append(logo)

                story.append(
                    Spacer(1, 3 * mm)
                )

            except Exception:
                pass

        story.append(
            Paragraph(
                business_settings.business_name,
                business_name_style
            )
        )

        business_info = []

        if business_settings.phone:
            business_info.append(
                f'Phone: {business_settings.phone}'
            )

        if business_settings.email:
            business_info.append(
                f'Email: {business_settings.email}'
            )

        if business_settings.address:
            business_info.append(
                f'Address: {business_settings.address}'
            )

        if business_info:

            story.append(
                Paragraph(
                    '<br/>'.join(business_info),
                    business_info_style
                )
            )

    # =========================================================
    # REPORT TITLE
    # =========================================================

    story.append(
        Paragraph(
            'Production Report',
            report_title_style
        )
    )

    story.append(
        Paragraph(
            f'Report Period: {start_date} to {end_date}',
            normal
        )
    )

    story.append(
        Spacer(1, 5 * mm)
    )

    # =========================================================
    # PRODUCTION SUMMARY
    # =========================================================

    planned_quantity = 0
    actual_quantity = 0

    completed_count = 0
    in_progress_count = 0
    planned_count = 0
    cancelled_count = 0

    for production in productions:

        if production.status == Production.Status.COMPLETED:
            completed_count += 1

        elif production.status == Production.Status.IN_PROGRESS:
            in_progress_count += 1

        elif production.status == Production.Status.PLANNED:
            planned_count += 1

        elif production.status == Production.Status.CANCELLED:
            cancelled_count += 1

        for item in production.items.all():

            planned_quantity += item.planned_quantity
            actual_quantity += item.actual_quantity

    summary_data = [
        [
            'Number of Productions',
            str(productions.count())
        ],
        [
            'Planned Quantity',
            f'{planned_quantity:.2f}'
        ],
        [
            'Actual Quantity',
            f'{actual_quantity:.2f}'
        ],
        [
            'Completed',
            str(completed_count)
        ],
        [
            'In Progress',
            str(in_progress_count)
        ],
        [
            'Planned',
            str(planned_count)
        ],
        [
            'Cancelled',
            str(cancelled_count)
        ],
    ]

    summary_table = Table(
        summary_data,
        colWidths=[50 * mm, 40 * mm]
    )

    summary_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (0, -1),
                colors.HexColor('#f8fafb')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, -1),
                colors.HexColor('#17324d')
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, -1),
                'Helvetica'
            ),
            (
                'FONTNAME',
                (0, 0),
                (0, -1),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor('#e5e9ed')
            ),
            (
                'PADDING',
                (0, 0),
                (-1, -1),
                6
            ),
        ])
    )

    story.append(summary_table)

    story.append(
        Spacer(1, 7 * mm)
    )

    # =========================================================
    # PRODUCTION RECORDS
    # =========================================================

    story.append(
        Paragraph(
            'Production Records',
            styles['Heading2']
        )
    )

    story.append(
        Spacer(1, 3 * mm)
    )

    table_data = [
        [
            'Production Date',
            'Created By',
            'Products',
            'Planned Quantity',
            'Actual Quantity',
            'Status',
        ]
    ]

    for production in productions:

        products = ', '.join(
            item.product.name
            for item in production.items.all()
        )

        planned_quantities = ', '.join(
            str(item.planned_quantity)
            for item in production.items.all()
        )

        actual_quantities = ', '.join(
            str(item.actual_quantity)
            for item in production.items.all()
        )

        table_data.append([
            production.production_date.strftime(
                '%d %b %Y'
            ),
            production.created_by.username,
            products,
            planned_quantities,
            actual_quantities,
            production.get_status_display(),
        ])

    production_table = Table(
        table_data,
        repeatRows=1,
        colWidths=[
            32 * mm,
            35 * mm,
            65 * mm,
            35 * mm,
            35 * mm,
            30 * mm,
        ],
    )

    production_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'FONTSIZE',
                (0, 0),
                (-1, -1),
                8
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor('#d9dee3')
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
            (
                'ROWBACKGROUNDS',
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor('#f8fafb')
                ]
            ),
            (
                'PADDING',
                (0, 0),
                (-1, -1),
                5
            ),
        ])
    )

    story.append(production_table)

    document.build(story)

    return response

def owner_stock_report(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    products = Product.objects.filter(
        is_available=True
    ).order_by(
        'name'
    )

    stock_items = []

    total_produced = 0
    total_sold = 0
    total_available = 0

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity - sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        stock_items.append({
            'product': product,
            'produced_quantity': produced_quantity,
            'sold_quantity': sold_quantity,
            'available_quantity': available_quantity,
        })

        total_produced += produced_quantity
        total_sold += sold_quantity
        total_available += available_quantity

    context = {
        'business_settings': business_settings,

        'stock_items': stock_items,
        'products_count': products.count(),
        'total_produced': total_produced,
        'total_sold': total_sold,
        'total_available': total_available,
    }

    return render(
        request,
        'bekapp/owner_stock_report.html',
        context
    )

# =========================================================
# OWNER STOCK REPORT - CSV
# =========================================================

def owner_stock_report_csv(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    products = Product.objects.filter(
        is_available=True
    ).order_by(
        'name'
    )

    business_settings = BusinessSettings.objects.first()

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        'attachment; filename="stock_report.csv"'
    )

    writer = csv.writer(response)

    # BUSINESS INFORMATION
    if business_settings:
        writer.writerow([
            'Business Name',
            business_settings.business_name
        ])
        writer.writerow([
            'Phone',
            business_settings.phone
        ])
        writer.writerow([
            'Email',
            business_settings.email
        ])
        writer.writerow([
            'Address',
            business_settings.address
        ])
    else:
        writer.writerow([
            'Business Name',
            'Bakery Management'
        ])

    writer.writerow([])

    # REPORT INFORMATION
    writer.writerow([
        'Stock Report'
    ])

    writer.writerow([])

    # TABLE HEADERS
    writer.writerow([
        'Product',
        'Produced',
        'Sold',
        'Available Stock',
    ])

    # STOCK DATA
    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity - sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        writer.writerow([
            product.name,
            produced_quantity,
            sold_quantity,
            available_quantity,
        ])

    return response




# =========================================================
# OWNER STOCK REPORT - EXCEL
# =========================================================


def owner_stock_report_excel(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    products = Product.objects.filter(
        is_available=True
    ).order_by(
        'name'
    )

    business_settings = BusinessSettings.objects.first()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Stock Report'

    # -------------------------------------------------
    # BUSINESS INFORMATION
    # -------------------------------------------------

    current_row = 1

    if business_settings:

        worksheet.cell(
            row=current_row,
            column=1,
            value=business_settings.business_name
        )

        worksheet.cell(
            row=current_row,
            column=1
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

        if business_settings.phone:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Phone: {business_settings.phone}'
            )
            current_row += 1

        if business_settings.email:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Email: {business_settings.email}'
            )
            current_row += 1

        if business_settings.address:
            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Address: {business_settings.address}'
            )
            current_row += 1

        # BUSINESS LOGO
        if business_settings.logo:
            try:
                logo = ExcelImage(
                    business_settings.logo.path
                )

                logo.width = 120
                logo.height = 70

                worksheet.add_image(
                    logo,
                    'E1'
                )

            except Exception:
                pass

    else:

        worksheet.cell(
            row=current_row,
            column=1,
            value='Bakery Management'
        )

        worksheet.cell(
            row=current_row,
            column=1
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

    # -------------------------------------------------
    # REPORT TITLE
    # -------------------------------------------------

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Stock Report'
    )

    worksheet.cell(
        row=current_row,
        column=1
    ).font = Font(
        bold=True,
        size=14
    )

    current_row += 2

    # -------------------------------------------------
    # TABLE HEADERS
    # -------------------------------------------------

    headers = [
        'Product',
        'Produced',
        'Sold',
        'Available Stock',
    ]

    for column_number, header in enumerate(
        headers,
        start=1
    ):

        cell = worksheet.cell(
            row=current_row,
            column=column_number,
            value=header
        )

        cell.font = Font(
            bold=True
        )

        cell.alignment = Alignment(
            horizontal='center',
            vertical='center'
        )

        cell.fill = PatternFill(
            fill_type='solid',
            fgColor='159A96'
        )

        cell.border = Border(
            bottom=Side(
                style='thin'
            )
        )

    # -------------------------------------------------
    # STOCK DATA
    # -------------------------------------------------

    data_start_row = current_row + 1

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity - sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        current_row += 1

        worksheet.cell(
            row=current_row,
            column=1,
            value=product.name
        )

        worksheet.cell(
            row=current_row,
            column=2,
            value=float(produced_quantity)
        )

        worksheet.cell(
            row=current_row,
            column=3,
            value=float(sold_quantity)
        )

        worksheet.cell(
            row=current_row,
            column=4,
            value=float(available_quantity)
        )

    # -------------------------------------------------
    # FORMATTING
    # -------------------------------------------------

    worksheet.freeze_panes = f'A{data_start_row}'

    worksheet.column_dimensions['A'].width = 30
    worksheet.column_dimensions['B'].width = 18
    worksheet.column_dimensions['C'].width = 18
    worksheet.column_dimensions['D'].width = 20

    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row,
        min_col=2,
        max_col=4
    ):
        for cell in row:
            cell.number_format = '#,##0.00'
            cell.alignment = Alignment(
                horizontal='center',
                vertical='center'
            )

    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row,
        min_col=1,
        max_col=1
    ):
        for cell in row:
            cell.alignment = Alignment(
                vertical='center'
            )

    # -------------------------------------------------
    # RESPONSE
    # -------------------------------------------------

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        'attachment; filename="stock_report.xlsx"'
    )

    workbook.save(response)

    return response



# =========================================================
# OWNER STOCK REPORT - PDF
# =========================================================
def owner_stock_report_pdf(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    products = Product.objects.filter(
        is_available=True
    ).order_by(
        'name'
    )

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        'attachment; filename="stock_report.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=10 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()

    elements = []

    # =========================================================
    # BUSINESS INFORMATION STYLES
    # =========================================================

    business_name_style = ParagraphStyle(
        'StockBusinessName',
        parent=styles['Title'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceAfter=4,
    )

    business_info_style = ParagraphStyle(
        'StockBusinessInfo',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#6c757d'),
        alignment=1,
    )

    report_title_style = ParagraphStyle(
        'StockReportTitle',
        parent=styles['Heading2'],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceBefore=8,
        spaceAfter=5,
    )

    normal = styles['Normal']
    normal.fontSize = 9

    # =========================================================
    # BUSINESS INFORMATION
    # =========================================================

    if business_settings:

        if business_settings.logo:

            try:

                logo = Image(
                    business_settings.logo.path,
                    width=28 * mm,
                    height=23 * mm,
                )

                logo.hAlign = 'CENTER'

                elements.append(logo)

                elements.append(
                    Spacer(1, 3 * mm)
                )

            except Exception:
                pass

        elements.append(
            Paragraph(
                business_settings.business_name,
                business_name_style
            )
        )

        business_info = []

        if business_settings.phone:
            business_info.append(
                f'Phone: {business_settings.phone}'
            )

        if business_settings.email:
            business_info.append(
                f'Email: {business_settings.email}'
            )

        if business_settings.address:
            business_info.append(
                f'Address: {business_settings.address}'
            )

        if business_info:

            elements.append(
                Paragraph(
                    '<br/>'.join(business_info),
                    business_info_style
                )
            )

    # =========================================================
    # REPORT TITLE
    # =========================================================

    elements.append(
        Paragraph(
            'Stock Report',
            report_title_style
        )
    )

    elements.append(
        Paragraph(
            'Current finished-product stock',
            normal
        )
    )

    elements.append(
        Spacer(1, 8 * mm)
    )

    # =========================================================
    # STOCK TABLE
    # =========================================================

    table_data = [
        [
            'Product',
            'Produced',
            'Sold',
            'Available Stock',
        ]
    ]

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity - sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        table_data.append([
            product.name,
            f'{produced_quantity:.2f}',
            f'{sold_quantity:.2f}',
            f'{available_quantity:.2f}',
        ])

    table = Table(
        table_data,
        colWidths=[
            100 * mm,
            40 * mm,
            40 * mm,
            50 * mm,
        ]
    )

    table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.5,
                colors.grey
            ),
            (
                'ALIGN',
                (1, 1),
                (-1, -1),
                'CENTER'
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
            (
                'BOTTOMPADDING',
                (0, 0),
                (-1, 0),
                8
            ),
            (
                'TOPPADDING',
                (0, 0),
                (-1, 0),
                8
            ),
        ])
    )

    elements.append(table)

    document.build(elements)

    return response

# =========================================================
# OWNER SPECIAL ORDER REPORT
# =========================================================

def owner_special_order_report(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    ).select_related(
        'customer',
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    total_amount = 0
    total_deposit = 0
    total_balance = 0

    pending_count = 0
    confirmed_count = 0
    in_production_count = 0
    ready_count = 0
    completed_count = 0
    cancelled_count = 0

    for order in special_orders:

        total_amount += order.total_amount
        total_deposit += order.deposit_amount

        balance = (
            order.total_amount -
            order.deposit_amount
        )

        if balance < 0:
            balance = 0

        total_balance += balance

        if order.status == SpecialOrder.Status.PENDING:
            pending_count += 1

        elif order.status == SpecialOrder.Status.CONFIRMED:
            confirmed_count += 1

        elif order.status == SpecialOrder.Status.IN_PRODUCTION:
            in_production_count += 1

        elif order.status == SpecialOrder.Status.READY:
            ready_count += 1

        elif order.status == SpecialOrder.Status.COMPLETED:
            completed_count += 1

        elif order.status == SpecialOrder.Status.CANCELLED:
            cancelled_count += 1

        order.report_balance = balance

    context = {
        'business_settings': business_settings,

        'start_date': start_date,
        'end_date': start_date,

        'special_orders': special_orders,
        'orders_count': special_orders.count(),

        'total_amount': total_amount,
        'total_deposit': total_deposit,
        'total_balance': total_balance,

        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'in_production_count': in_production_count,
        'ready_count': ready_count,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
    }

    return render(
        request,
        'bekapp/owner_special_order_report.html',
        context
    )


def owner_special_order_report_csv(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    ).select_related(
        'customer',
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    business_settings = BusinessSettings.objects.first()

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="special_order_report_'
        f'{start_date}_to_{end_date}.csv"'
    )

    writer = csv.writer(response)

    # BUSINESS INFORMATION
    if business_settings:
        writer.writerow([
            'Business Name',
            business_settings.business_name
        ])
        writer.writerow([
            'Phone',
            business_settings.phone
        ])
        writer.writerow([
            'Email',
            business_settings.email
        ])
        writer.writerow([
            'Address',
            business_settings.address
        ])
    else:
        writer.writerow([
            'Business Name',
            'Bakery Management'
        ])

    writer.writerow([])

    # REPORT INFORMATION
    writer.writerow([
        'Special Orders Report'
    ])

    writer.writerow([
        'Report Period',
        f'{start_date} to {end_date}'
    ])

    writer.writerow([])

    # TABLE HEADERS
    writer.writerow([
        'Order Number',
        'Customer',
        'Phone',
        'Event Type',
        'Event Date',
        'Pickup Time',
        'Products',
        'Total Amount',
        'Deposit',
        'Balance',
        'Status',
    ])

    # SPECIAL ORDER DATA
    for order in special_orders:

        balance = (
            order.total_amount -
            order.deposit_amount
        )

        if balance < 0:
            balance = 0

        products = ', '.join(
            f'{item.product.name} x {item.quantity}'
            for item in order.items.all()
        )

        writer.writerow([
            order.order_number,
            order.customer.name,
            order.customer.phone,
            order.get_event_type_display(),
            order.event_date,
            order.pickup_time or '',
            products,
            order.total_amount,
            order.deposit_amount,
            balance,
            order.get_status_display(),
        ])

    return response



def owner_special_order_report_excel(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    ).select_related(
        'customer',
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    business_settings = BusinessSettings.objects.first()

    workbook = Workbook()

    worksheet = workbook.active
    worksheet.title = 'Special Orders'

    # -------------------------------------------------
    # BUSINESS INFORMATION
    # -------------------------------------------------

    current_row = 1

    if business_settings:

        # BUSINESS LOGO
        if business_settings.logo:
            logo = ExcelImage(
                business_settings.logo.path
            )

            logo.width = 120
            logo.height = 70

            worksheet.add_image(
                logo,
                'A1'
            )

        # BUSINESS NAME
        worksheet.cell(
            row=current_row,
            column=3,
            value=business_settings.business_name
        )

        worksheet.cell(
            row=current_row,
            column=3
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

        # PHONE
        if business_settings.phone:
            worksheet.cell(
                row=current_row,
                column=3,
                value=f'Phone: {business_settings.phone}'
            )
            current_row += 1

        # EMAIL
        if business_settings.email:
            worksheet.cell(
                row=current_row,
                column=3,
                value=f'Email: {business_settings.email}'
            )
            current_row += 1

        # ADDRESS
        if business_settings.address:
            worksheet.cell(
                row=current_row,
                column=3,
                value=f'Address: {business_settings.address}'
            )
            current_row += 1

    else:

        worksheet.cell(
            row=current_row,
            column=3,
            value='Bakery Management'
        )

        worksheet.cell(
            row=current_row,
            column=3
        ).font = Font(
            bold=True,
            size=16
        )

        current_row += 1

    # -------------------------------------------------
    # REPORT TITLE
    # -------------------------------------------------

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Special Orders Report'
    )

    worksheet.cell(
        row=current_row,
        column=1
    ).font = Font(
        bold=True,
        size=14
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Report Period'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=f'{start_date} to {end_date}'
    )

    current_row += 2

    # -------------------------------------------------
    # TABLE HEADERS
    # -------------------------------------------------

    headers = [
        'Order Number',
        'Customer',
        'Phone',
        'Event Type',
        'Event Date',
        'Pickup Time',
        'Products',
        'Total Amount',
        'Deposit',
        'Balance',
        'Status',
    ]

    for column_number, header in enumerate(
        headers,
        start=1
    ):

        cell = worksheet.cell(
            row=current_row,
            column=column_number,
            value=header
        )

        cell.font = Font(
            bold=True,
            color='FFFFFF'
        )

        cell.alignment = Alignment(
            horizontal='center',
            vertical='center'
        )

        cell.fill = PatternFill(
            fill_type='solid',
            fgColor='159A96'
        )

        cell.border = Border(
            bottom=Side(
                style='thin'
            )
        )

    # -------------------------------------------------
    # SPECIAL ORDER DATA
    # -------------------------------------------------

    data_start_row = current_row + 1

    for order in special_orders:

        balance = (
            order.total_amount -
            order.deposit_amount
        )

        if balance < 0:
            balance = 0

        products = ', '.join(
            f'{item.product.name} x {item.quantity}'
            for item in order.items.all()
        )

        current_row += 1

        worksheet.cell(
            row=current_row,
            column=1,
            value=order.order_number
        )

        worksheet.cell(
            row=current_row,
            column=2,
            value=order.customer.name
        )

        worksheet.cell(
            row=current_row,
            column=3,
            value=order.customer.phone
        )

        worksheet.cell(
            row=current_row,
            column=4,
            value=order.get_event_type_display()
        )

        worksheet.cell(
            row=current_row,
            column=5,
            value=order.event_date
        )

        worksheet.cell(
            row=current_row,
            column=6,
            value=str(order.pickup_time or '')
        )

        worksheet.cell(
            row=current_row,
            column=7,
            value=products
        )

        worksheet.cell(
            row=current_row,
            column=8,
            value=float(order.total_amount)
        )

        worksheet.cell(
            row=current_row,
            column=9,
            value=float(order.deposit_amount)
        )

        worksheet.cell(
            row=current_row,
            column=10,
            value=float(balance)
        )

        worksheet.cell(
            row=current_row,
            column=11,
            value=order.get_status_display()
        )

    # -------------------------------------------------
    # FORMATTING
    # -------------------------------------------------

    worksheet.freeze_panes = f'A{data_start_row}'

    column_widths = {
        'A': 25,
        'B': 25,
        'C': 20,
        'D': 18,
        'E': 15,
        'F': 15,
        'G': 45,
        'H': 18,
        'I': 18,
        'J': 18,
        'K': 18,
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[
            column
        ].width = width

    # Logo row height
    worksheet.row_dimensions[1].height = 60

    # Amount formatting
    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row,
        min_col=8,
        max_col=10
    ):
        for cell in row:
            cell.number_format = '#,##0.00'
            cell.alignment = Alignment(
                horizontal='center',
                vertical='center'
            )

    # General alignment
    for row in worksheet.iter_rows(
        min_row=data_start_row,
        max_row=worksheet.max_row
    ):
        for cell in row:
            cell.alignment = Alignment(
                vertical='center',
                wrap_text=True
            )

    # -------------------------------------------------
    # RESPONSE
    # -------------------------------------------------

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        f'attachment; filename="special_order_report_'
        f'{start_date}_to_{end_date}.xlsx"'
    )

    workbook.save(response)

    return response




def owner_special_order_report_pdf(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    ).select_related(
        'customer',
        'created_by'
    ).prefetch_related(
        'items__product'
    )

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        'attachment; filename="special_order_report.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()

    elements = []

    # =========================================================
    # BUSINESS HEADER STYLES
    # =========================================================

    business_name_style = ParagraphStyle(
        'SpecialOrderBusinessName',
        parent=styles['Title'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceAfter=4,
    )

    business_info_style = ParagraphStyle(
        'SpecialOrderBusinessInfo',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#6c757d'),
        alignment=1,
    )

    report_title_style = ParagraphStyle(
        'SpecialOrderReportTitle',
        parent=styles['Heading2'],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceBefore=8,
        spaceAfter=5,
    )

    normal = styles['Normal']
    normal.fontSize = 9

    # =========================================================
    # BUSINESS INFORMATION
    # =========================================================

    if business_settings:

        if business_settings.logo:

            try:

                logo = Image(
                    business_settings.logo.path,
                    width=28 * mm,
                    height=23 * mm,
                )

                logo.hAlign = 'CENTER'

                elements.append(logo)

                elements.append(
                    Spacer(1, 3 * mm)
                )

            except Exception:
                pass

        elements.append(
            Paragraph(
                business_settings.business_name,
                business_name_style
            )
        )

        business_info = []

        if business_settings.phone:
            business_info.append(
                f'Phone: {business_settings.phone}'
            )

        if business_settings.email:
            business_info.append(
                f'Email: {business_settings.email}'
            )

        if business_settings.address:
            business_info.append(
                f'Address: {business_settings.address}'
            )

        if business_info:

            elements.append(
                Paragraph(
                    '<br/>'.join(business_info),
                    business_info_style
                )
            )

    # =========================================================
    # REPORT TITLE
    # =========================================================

    elements.append(
        Paragraph(
            'Special Order Report',
            report_title_style
        )
    )

    elements.append(
        Paragraph(
            f'Report Period: {start_date} to {end_date}',
            normal
        )
    )

    elements.append(
        Spacer(1, 8 * mm)
    )

    # =========================================================
    # REPORT TABLE
    # =========================================================

    table_data = [
        [
            'Order',
            'Customer',
            'Event',
            'Event Date',
            'Pickup',
            'Products',
            'Total',
            'Deposit',
            'Balance',
            'Status',
        ]
    ]

    for order in special_orders:

        balance = (
            order.total_amount -
            order.deposit_amount
        )

        if balance < 0:
            balance = 0

        products = ', '.join(
            f'{item.product.name} x {item.quantity}'
            for item in order.items.all()
        )

        table_data.append([
            order.order_number,
            order.customer.name,
            order.get_event_type_display(),
            order.event_date.strftime('%d %b %Y'),
            (
                order.pickup_time.strftime('%H:%M')
                if order.pickup_time
                else '-'
            ),
            products,
            f'{order.total_amount:.2f}',
            f'{order.deposit_amount:.2f}',
            f'{balance:.2f}',
            order.get_status_display(),
        ])

    table = Table(
        table_data,
        colWidths=[
            25 * mm,
            30 * mm,
            25 * mm,
            27 * mm,
            18 * mm,
            55 * mm,
            22 * mm,
            22 * mm,
            22 * mm,
            27 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'FONTSIZE',
                (0, 0),
                (-1, -1),
                7
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.4,
                colors.grey
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
            (
                'ALIGN',
                (6, 1),
                (8, -1),
                'RIGHT'
            ),
            (
                'BOTTOMPADDING',
                (0, 0),
                (-1, 0),
                7
            ),
            (
                'TOPPADDING',
                (0, 0),
                (-1, 0),
                7
            ),
        ])
    )

    elements.append(table)

    document.build(elements)

    return response

# =========================================================
# OWNER BUSINESS SUMMARY REPORT
# =========================================================


def owner_business_summary(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()


    # =====================================================
    # SALES
    # =====================================================

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    )

    total_sales = sum(
        sale.total_amount
        for sale in sales
    )

    total_discount = sum(
        sale.discount
        for sale in sales
    )

    sales_count = sales.count()


    # =====================================================
    # PAYMENTS
    # =====================================================

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    )

    total_paid = sum(
        payment.amount
        for payment in payments
        if payment.status == Payment.Status.PAID
    )


    # =====================================================
    # PRODUCTION
    # =====================================================

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    )

    production_count = productions.count()

    completed_production_count = productions.filter(
        status=Production.Status.COMPLETED
    ).count()

    total_produced = sum(
        item.actual_quantity
        for production in productions
        for item in production.items.all()
        if production.status == Production.Status.COMPLETED
    )


    # =====================================================
    # SPECIAL ORDERS
    # =====================================================

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    )

    special_order_count = special_orders.count()

    special_order_total = sum(
        order.total_amount
        for order in special_orders
    )

    special_order_deposit = sum(
        order.deposit_amount
        for order in special_orders
    )

    special_order_balance = (
        special_order_total -
        special_order_deposit
    )

    if special_order_balance < 0:
        special_order_balance = 0


    # =====================================================
    # CURRENT STOCK
    # =====================================================

    products = Product.objects.filter(
        is_available=True
    )

    total_stock_available = 0

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity -
            sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        total_stock_available += available_quantity


    # =====================================================
    # CONTEXT
    # =====================================================

    context = {

        'business_settings': business_settings,

        'start_date': start_date,
        'end_date': end_date,

        # Sales
        'sales_count': sales_count,
        'total_sales': total_sales,
        'total_discount': total_discount,

        # Payments
        'total_paid': total_paid,

        # Production
        'production_count': production_count,
        'completed_production_count': completed_production_count,
        'total_produced': total_produced,

        # Special Orders
        'special_order_count': special_order_count,
        'special_order_total': special_order_total,
        'special_order_deposit': special_order_deposit,
        'special_order_balance': special_order_balance,

        # Stock
        'total_stock_available': total_stock_available,
    }

    return render(
        request,
        'bekapp/owner_business_summary.html',
        context
    )



def owner_business_summary_pdf(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()


    # =====================================================
    # SALES
    # =====================================================

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    )

    total_sales = sum(
        sale.total_amount
        for sale in sales
    )

    total_discount = sum(
        sale.discount
        for sale in sales
    )

    sales_count = sales.count()


    # =====================================================
    # PAYMENTS
    # =====================================================

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    )

    total_paid = sum(
        payment.amount
        for payment in payments
        if payment.status == Payment.Status.PAID
    )


    # =====================================================
    # PRODUCTION
    # =====================================================

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    )

    production_count = productions.count()

    completed_production_count = productions.filter(
        status=Production.Status.COMPLETED
    ).count()

    total_produced = sum(
        item.actual_quantity
        for production in productions
        for item in production.items.all()
        if production.status == Production.Status.COMPLETED
    )


    # =====================================================
    # SPECIAL ORDERS
    # =====================================================

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    )

    special_order_count = special_orders.count()

    special_order_total = sum(
        order.total_amount
        for order in special_orders
    )

    special_order_deposit = sum(
        order.deposit_amount
        for order in special_orders
    )

    special_order_balance = (
        special_order_total -
        special_order_deposit
    )

    if special_order_balance < 0:
        special_order_balance = 0


    # =====================================================
    # CURRENT STOCK
    # =====================================================

    products = Product.objects.filter(
        is_available=True
    )

    total_stock_available = 0

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity -
            sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        total_stock_available += available_quantity


    # =====================================================
    # PDF RESPONSE
    # =====================================================

    response = HttpResponse(
        content_type='application/pdf'
    )

    response['Content-Disposition'] = (
        'attachment; filename="business_summary.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=10 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()

    elements = []


    # =====================================================
    # PDF STYLES
    # =====================================================

    business_name_style = ParagraphStyle(
        'BusinessSummaryBusinessName',
        parent=styles['Title'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceAfter=4,
    )

    business_info_style = ParagraphStyle(
        'BusinessSummaryBusinessInfo',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#6c757d'),
        alignment=1,
    )

    report_title_style = ParagraphStyle(
        'BusinessSummaryReportTitle',
        parent=styles['Heading2'],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#17324d'),
        alignment=1,
        spaceBefore=8,
        spaceAfter=5,
    )

    section_title_style = ParagraphStyle(
        'BusinessSummarySectionTitle',
        parent=styles['Heading3'],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#17324d'),
        spaceBefore=8,
        spaceAfter=5,
    )

    normal = styles['Normal']
    normal.fontSize = 9


    # =====================================================
    # BUSINESS HEADER
    # =====================================================

    if business_settings:

        if business_settings.logo:

            try:

                logo = Image(
                    business_settings.logo.path,
                    width=28 * mm,
                    height=23 * mm,
                )

                logo.hAlign = 'CENTER'

                elements.append(logo)

                elements.append(
                    Spacer(1, 3 * mm)
                )

            except Exception:
                pass

        elements.append(
            Paragraph(
                business_settings.business_name,
                business_name_style
            )
        )

        business_info = []

        if business_settings.phone:
            business_info.append(
                f'Phone: {business_settings.phone}'
            )

        if business_settings.email:
            business_info.append(
                f'Email: {business_settings.email}'
            )

        if business_settings.address:
            business_info.append(
                f'Address: {business_settings.address}'
            )

        if business_info:

            elements.append(
                Paragraph(
                    '<br/>'.join(business_info),
                    business_info_style
                )
            )


    # =====================================================
    # REPORT TITLE
    # =====================================================

    elements.append(
        Paragraph(
            'Business Summary',
            report_title_style
        )
    )

    elements.append(
        Paragraph(
            f'Report Period: {start_date} to {end_date}',
            normal
        )
    )

    elements.append(
        Spacer(1, 6 * mm)
    )


    # =====================================================
    # SALES SUMMARY
    # =====================================================

    elements.append(
        Paragraph(
            'Sales Summary',
            section_title_style
        )
    )

    sales_data = [
        ['Metric', 'Value'],
        ['Number of Sales', str(sales_count)],
        ['Total Sales', f'{total_sales:.2f} ETB'],
        ['Total Discount', f'{total_discount:.2f} ETB'],
        ['Total Paid', f'{total_paid:.2f} ETB'],
    ]

    sales_table = Table(
        sales_data,
        colWidths=[
            85 * mm,
            85 * mm,
        ],
    )

    sales_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.4,
                colors.grey
            ),
            (
                'ALIGN',
                (1, 1),
                (1, -1),
                'RIGHT'
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
        ])
    )

    elements.append(sales_table)


    # =====================================================
    # PRODUCTION SUMMARY
    # =====================================================

    elements.append(
        Paragraph(
            'Production Summary',
            section_title_style
        )
    )

    production_data = [
        ['Metric', 'Value'],
        ['Productions', str(production_count)],
        [
            'Completed Productions',
            str(completed_production_count)
        ],
        [
            'Total Produced',
            f'{total_produced:.2f}'
        ],
    ]

    production_table = Table(
        production_data,
        colWidths=[
            85 * mm,
            85 * mm,
        ],
    )

    production_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.4,
                colors.grey
            ),
            (
                'ALIGN',
                (1, 1),
                (1, -1),
                'RIGHT'
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
        ])
    )

    elements.append(production_table)


    # =====================================================
    # SPECIAL ORDERS SUMMARY
    # =====================================================

    elements.append(
        Paragraph(
            'Special Orders Summary',
            section_title_style
        )
    )

    special_order_data = [
        ['Metric', 'Value'],
        ['Special Orders', str(special_order_count)],
        [
            'Total Amount',
            f'{special_order_total:.2f} ETB'
        ],
        [
            'Total Deposits',
            f'{special_order_deposit:.2f} ETB'
        ],
        [
            'Outstanding Balance',
            f'{special_order_balance:.2f} ETB'
        ],
    ]

    special_order_table = Table(
        special_order_data,
        colWidths=[
            85 * mm,
            85 * mm,
        ],
    )

    special_order_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.4,
                colors.grey
            ),
            (
                'ALIGN',
                (1, 1),
                (1, -1),
                'RIGHT'
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
        ])
    )

    elements.append(special_order_table)


    # =====================================================
    # CURRENT STOCK
    # =====================================================

    elements.append(
        Paragraph(
            'Current Stock',
            section_title_style
        )
    )

    stock_data = [
        ['Metric', 'Value'],
        [
            'Available Finished Products',
            f'{total_stock_available:.2f}'
        ],
    ]

    stock_table = Table(
        stock_data,
        colWidths=[
            85 * mm,
            85 * mm,
        ],
    )

    stock_table.setStyle(
        TableStyle([
            (
                'BACKGROUND',
                (0, 0),
                (-1, 0),
                colors.HexColor('#159a96')
            ),
            (
                'TEXTCOLOR',
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                'FONTNAME',
                (0, 0),
                (-1, 0),
                'Helvetica-Bold'
            ),
            (
                'GRID',
                (0, 0),
                (-1, -1),
                0.4,
                colors.grey
            ),
            (
                'ALIGN',
                (1, 1),
                (1, -1),
                'RIGHT'
            ),
            (
                'VALIGN',
                (0, 0),
                (-1, -1),
                'MIDDLE'
            ),
        ])
    )

    elements.append(stock_table)


    # =====================================================
    # BUILD PDF
    # =====================================================

    document.build(elements)

    return response


def owner_business_summary_csv(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()

    # ---------------------------------------------------------
    # BUSINESS SETTINGS
    # ---------------------------------------------------------

    business_settings = BusinessSettings.objects.first()

    # ---------------------------------------------------------
    # SALES
    # ---------------------------------------------------------

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    )

    total_sales = sum(
        sale.total_amount
        for sale in sales
    )

    total_discount = sum(
        sale.discount
        for sale in sales
    )

    sales_count = sales.count()

    # ---------------------------------------------------------
    # PAYMENTS
    # ---------------------------------------------------------

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    )

    total_paid = sum(
        payment.amount
        for payment in payments
        if payment.status == Payment.Status.PAID
    )

    # ---------------------------------------------------------
    # PRODUCTION
    # ---------------------------------------------------------

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    )

    production_count = productions.count()

    completed_production_count = productions.filter(
        status=Production.Status.COMPLETED
    ).count()

    total_produced = sum(
        item.actual_quantity
        for production in productions
        for item in production.items.all()
        if production.status == Production.Status.COMPLETED
    )

    # ---------------------------------------------------------
    # SPECIAL ORDERS
    # ---------------------------------------------------------

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    )

    special_order_count = special_orders.count()

    special_order_total = sum(
        order.total_amount
        for order in special_orders
    )

    special_order_deposit = sum(
        order.deposit_amount
        for order in special_orders
    )

    special_order_balance = (
        special_order_total -
        special_order_deposit
    )

    if special_order_balance < 0:
        special_order_balance = 0

    # ---------------------------------------------------------
    # CURRENT STOCK
    # ---------------------------------------------------------

    products = Product.objects.filter(
        is_available=True
    )

    total_stock_available = 0

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity -
            sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        total_stock_available += available_quantity

    # ---------------------------------------------------------
    # CSV RESPONSE
    # ---------------------------------------------------------

    response = HttpResponse(
        content_type='text/csv; charset=utf-8'
    )

    response['Content-Disposition'] = (
        f'attachment; filename="business_summary_'
        f'{start_date}_to_{end_date}.csv"'
    )

    writer = csv.writer(response)

    # ---------------------------------------------------------
    # BUSINESS INFORMATION
    # ---------------------------------------------------------

    if business_settings:

        writer.writerow([
            'Business Name',
            business_settings.business_name
        ])

        writer.writerow([
            'Phone',
            business_settings.phone
        ])

        writer.writerow([
            'Email',
            business_settings.email
        ])

        writer.writerow([
            'Address',
            business_settings.address
        ])

    else:

        writer.writerow([
            'Business Name',
            'Bakery Management'
        ])

    writer.writerow([])

    # ---------------------------------------------------------
    # REPORT INFORMATION
    # ---------------------------------------------------------

    writer.writerow([
        'Business Summary'
    ])

    writer.writerow([
        'Report Period',
        f'{start_date} to {end_date}'
    ])

    writer.writerow([])

    # ---------------------------------------------------------
    # SALES SUMMARY
    # ---------------------------------------------------------

    writer.writerow([
        'SALES SUMMARY'
    ])

    writer.writerow([
        'Metric',
        'Value'
    ])

    writer.writerow([
        'Number of Sales',
        sales_count
    ])

    writer.writerow([
        'Total Sales',
        f'{total_sales:.2f}'
    ])

    writer.writerow([
        'Total Discount',
        f'{total_discount:.2f}'
    ])

    writer.writerow([
        'Total Paid',
        f'{total_paid:.2f}'
    ])

    writer.writerow([])

    # ---------------------------------------------------------
    # PRODUCTION SUMMARY
    # ---------------------------------------------------------

    writer.writerow([
        'PRODUCTION SUMMARY'
    ])

    writer.writerow([
        'Metric',
        'Value'
    ])

    writer.writerow([
        'Productions',
        production_count
    ])

    writer.writerow([
        'Completed Productions',
        completed_production_count
    ])

    writer.writerow([
        'Total Produced',
        f'{total_produced:.2f}'
    ])

    writer.writerow([])

    # ---------------------------------------------------------
    # SPECIAL ORDERS SUMMARY
    # ---------------------------------------------------------

    writer.writerow([
        'SPECIAL ORDERS SUMMARY'
    ])

    writer.writerow([
        'Metric',
        'Value'
    ])

    writer.writerow([
        'Special Orders',
        special_order_count
    ])

    writer.writerow([
        'Total Amount',
        f'{special_order_total:.2f}'
    ])

    writer.writerow([
        'Total Deposits',
        f'{special_order_deposit:.2f}'
    ])

    writer.writerow([
        'Outstanding Balance',
        f'{special_order_balance:.2f}'
    ])

    writer.writerow([])

    # ---------------------------------------------------------
    # CURRENT STOCK
    # ---------------------------------------------------------

    writer.writerow([
        'CURRENT STOCK'
    ])

    writer.writerow([
        'Metric',
        'Value'
    ])

    writer.writerow([
        'Available Finished Products',
        f'{total_stock_available:.2f}'
    ])

    return response




def owner_business_summary_excel(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    business_settings = BusinessSettings.objects.first()

    today = timezone.localdate()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = today.replace(day=1).isoformat()

    if not end_date:
        end_date = today.isoformat()


    # =====================================================
    # SALES
    # =====================================================

    sales = Sale.objects.filter(
        sale_date__date__range=[start_date, end_date]
    )

    total_sales = sum(
        sale.total_amount
        for sale in sales
    )

    total_discount = sum(
        sale.discount
        for sale in sales
    )

    sales_count = sales.count()


    # =====================================================
    # PAYMENTS
    # =====================================================

    payments = Payment.objects.filter(
        payment_date__date__range=[start_date, end_date]
    )

    total_paid = sum(
        payment.amount
        for payment in payments
        if payment.status == Payment.Status.PAID
    )


    # =====================================================
    # PRODUCTION
    # =====================================================

    productions = Production.objects.filter(
        production_date__range=[start_date, end_date]
    )

    production_count = productions.count()

    completed_production_count = productions.filter(
        status=Production.Status.COMPLETED
    ).count()

    total_produced = sum(
        item.actual_quantity
        for production in productions
        for item in production.items.all()
        if production.status == Production.Status.COMPLETED
    )


    # =====================================================
    # SPECIAL ORDERS
    # =====================================================

    special_orders = SpecialOrder.objects.filter(
        event_date__range=[start_date, end_date]
    )

    special_order_count = special_orders.count()

    special_order_total = sum(
        order.total_amount
        for order in special_orders
    )

    special_order_deposit = sum(
        order.deposit_amount
        for order in special_orders
    )

    special_order_balance = (
        special_order_total -
        special_order_deposit
    )

    if special_order_balance < 0:
        special_order_balance = 0


    # =====================================================
    # CURRENT STOCK
    # =====================================================

    products = Product.objects.filter(
        is_available=True
    )

    total_stock_available = 0

    for product in products:

        produced_quantity = sum(
            item.actual_quantity
            for item in product.production_items.filter(
                production__status=Production.Status.COMPLETED
            )
        )

        sold_quantity = sum(
            item.quantity
            for item in product.sale_items.all()
        )

        available_quantity = (
            produced_quantity -
            sold_quantity
        )

        if available_quantity < 0:
            available_quantity = 0

        total_stock_available += available_quantity


    # =====================================================
    # CREATE EXCEL WORKBOOK
    # =====================================================

    workbook = Workbook()

    worksheet = workbook.active

    worksheet.title = 'Business Summary'


    # =====================================================
    # BUSINESS INFORMATION
    # =====================================================

    current_row = 1

    if business_settings:

        # BUSINESS LOGO
        if business_settings.logo:

            try:

                logo = ExcelImage(
                    business_settings.logo.path
                )

                logo.width = 140
                logo.height = 105

                worksheet.add_image(
                    logo,
                    'A1'
                )

                current_row = 8

            except Exception:

                current_row = 1


        # BUSINESS NAME
        if business_settings.business_name:

            worksheet.cell(
                row=current_row,
                column=1,
                value=business_settings.business_name
            )

            current_row += 1


        # PHONE
        if business_settings.phone:

            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Phone: {business_settings.phone}'
            )

            current_row += 1


        # EMAIL
        if business_settings.email:

            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Email: {business_settings.email}'
            )

            current_row += 1


        # ADDRESS
        if business_settings.address:

            worksheet.cell(
                row=current_row,
                column=1,
                value=f'Address: {business_settings.address}'
            )

            current_row += 1


    current_row += 1


    # =====================================================
    # REPORT TITLE
    # =====================================================

    report_title_row = current_row

    worksheet.cell(
        row=current_row,
        column=1,
        value='Business Summary'
    )

    current_row += 1


    # =====================================================
    # REPORT PERIOD
    # =====================================================

    worksheet.cell(
        row=current_row,
        column=1,
        value='Report Period'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=f'{start_date} to {end_date}'
    )

    current_row += 2


    # =====================================================
    # SALES SUMMARY
    # =====================================================

    sales_section_row = current_row

    worksheet.cell(
        row=current_row,
        column=1,
        value='SALES SUMMARY'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Metric'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value='Value'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Number of Sales'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=sales_count
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Total Sales'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(total_sales)
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Total Discount'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(total_discount)
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Total Paid'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(total_paid)
    )

    current_row += 2


    # =====================================================
    # PRODUCTION SUMMARY
    # =====================================================

    production_section_row = current_row

    worksheet.cell(
        row=current_row,
        column=1,
        value='PRODUCTION SUMMARY'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Metric'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value='Value'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Productions'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=production_count
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Completed Productions'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=completed_production_count
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Total Produced'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(total_produced)
    )

    current_row += 2


    # =====================================================
    # SPECIAL ORDERS SUMMARY
    # =====================================================

    special_order_section_row = current_row

    worksheet.cell(
        row=current_row,
        column=1,
        value='SPECIAL ORDERS SUMMARY'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Metric'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value='Value'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Special Orders'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=special_order_count
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Total Amount'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(special_order_total)
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Total Deposits'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(special_order_deposit)
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Outstanding Balance'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(special_order_balance)
    )

    current_row += 2


    # =====================================================
    # CURRENT STOCK
    # =====================================================

    stock_section_row = current_row

    worksheet.cell(
        row=current_row,
        column=1,
        value='CURRENT STOCK'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Metric'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value='Value'
    )

    current_row += 1

    worksheet.cell(
        row=current_row,
        column=1,
        value='Available Finished Products'
    )

    worksheet.cell(
        row=current_row,
        column=2,
        value=float(total_stock_available)
    )


    # =====================================================
    # EXCEL STYLING
    # =====================================================

    teal_fill = PatternFill(
        fill_type='solid',
        fgColor='159A96',
    )

    light_teal_fill = PatternFill(
        fill_type='solid',
        fgColor='EAF7F7',
    )

    white_font = Font(
        color='FFFFFF',
        bold=True,
    )

    business_name_font = Font(
        size=18,
        bold=True,
    )

    report_title_font = Font(
        size=15,
        bold=True,
    )

    section_font = Font(
        size=12,
        bold=True,
        color='FFFFFF',
    )

    header_font = Font(
        bold=True,
    )

    thin_side = Side(
        style='thin',
        color='D9E1E2',
    )

    section_border = Border(
        bottom=thin_side,
    )


    # =====================================================
    # BUSINESS NAME
    # =====================================================

    business_name_row = 8

    if (
        business_settings
        and business_settings.business_name
    ):

        cell = worksheet.cell(
            row=business_name_row,
            column=1,
        )

        cell.font = business_name_font

        cell.alignment = Alignment(
            vertical='center'
        )


    # =====================================================
    # REPORT TITLE
    # =====================================================

    worksheet.cell(
        row=report_title_row,
        column=1,
    ).font = report_title_font

    worksheet.cell(
        row=report_title_row,
        column=1,
    ).alignment = Alignment(
        vertical='center'
    )


    # =====================================================
    # SECTION HEADINGS
    # =====================================================

    for section_row in [
        sales_section_row,
        production_section_row,
        special_order_section_row,
        stock_section_row,
    ]:

        for column in range(1, 3):

            cell = worksheet.cell(
                row=section_row,
                column=column,
            )

            cell.fill = teal_fill

            cell.border = section_border

            cell.alignment = Alignment(
                vertical='center'
            )

        worksheet.cell(
            row=section_row,
            column=1,
        ).font = section_font


    # =====================================================
    # TABLE HEADERS
    # =====================================================

    for row in worksheet.iter_rows():

        for cell in row:

            if cell.value in [
                'Metric',
                'Value',
            ]:

                cell.font = header_font

                cell.fill = light_teal_fill

                cell.alignment = Alignment(
                    vertical='center'
                )

                cell.border = section_border


    # =====================================================
    # GENERAL ALIGNMENT
    # =====================================================

    for row in worksheet.iter_rows():

        for cell in row:

            if cell.value is not None:

                cell.alignment = Alignment(
                    vertical='center'
                )


    # =====================================================
    # COLUMN WIDTHS
    # =====================================================

    worksheet.column_dimensions['A'].width = 35
    worksheet.column_dimensions['B'].width = 28


    # =====================================================
    # ROW HEIGHTS
    # =====================================================

    worksheet.row_dimensions[1].height = 25
    worksheet.row_dimensions[8].height = 28


    # =====================================================
    # NUMBER FORMATTING
    # =====================================================

    for row in range(
        1,
        worksheet.max_row + 1
    ):

        cell = worksheet[f'B{row}']

        if isinstance(
            cell.value,
            (int, float)
        ):

            cell.number_format = '#,##0.00'


    # =====================================================
    # RESPONSE
    # =====================================================

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        )
    )

    response['Content-Disposition'] = (
        'attachment; filename="business_summary.xlsx"'
    )

    workbook.save(response)

    return response

def business_settings(request):

    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.role != 'OWNER':
        return redirect('dashboard')

    settings = BusinessSettings.objects.first()

    if request.method == 'POST':

        form = BusinessSettingsForm(
            request.POST,
            request.FILES,
            instance=settings,
        )

        if form.is_valid():
            form.save()

            return redirect(
                'business_settings'
            )

    else:

        form = BusinessSettingsForm(
            instance=settings
        )

    return render(
        request,
        'bekapp/business_settings.html',
        {
            'form': form,
        }
    )