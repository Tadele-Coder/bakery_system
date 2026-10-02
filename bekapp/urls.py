from django.urls import path
from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),

    path(
        'owner/dashboard/',
        views.owner_dashboard,
        name='owner_dashboard'
    ),

    path(
    'settings/',
    views.business_settings,
    name='business_settings',
    ),  

    path(
    'users/',
    views.user_list,
    name='user_list'
    ),

    path(
    'users/new/',
    views.staff_create,
    name='staff_create'
    ),

    path(
    'users/<int:user_id>/edit/',
    views.staff_edit,
    name='staff_edit'
    ), 

    path(
        'production/dashboard/',
        views.production_dashboard,
        name='production_dashboard'
    ),

    path(
        'production/',
        views.production_list,
        name='production_list'
    ),

    path(
    'production/completed/',
    views.production_completed_list,
    name='production_completed_list'
    ),

    path(
    'production/stock/',
    views.production_stock_list,
    name='production_stock_list'
    ),

    path(
    'production/new/',
    views.production_create,
    name='production_create'
    ),

    path(
    'production/<int:production_id>/start/',
    views.production_start,
    name='production_start'
    ),

    path(
        'production/<int:production_id>/complete/',
        views.production_complete,
        name='production_complete'
    ),

    path(
    'production/<int:production_id>/cancel/',
    views.production_cancel,
    name='production_cancel'
    ),

    path(
        'production/<int:production_id>/',
        views.production_detail,
        name='production_detail'
    ),


    path(
        'cashier/dashboard/',
        views.cashier_dashboard,
        name='cashier_dashboard'
    ),

    path(
    'sales/new/',
    views.sale_create,
    name='sale_create'
    ),

    path(
    'products/new/',
    views.product_create,
    name='product_create'
    ),

    path(
    'products/<int:product_id>/edit/',
    views.product_edit,
    name='product_edit'
    ),

    path(
    'products/<int:product_id>/toggle-status/',
    views.product_toggle_status,
    name='product_toggle_status'
    ),

    path(
    'products/<int:product_id>/delete/',
    views.product_delete,
    name='product_delete'
    ),

    path(
    'sales/',
    views.sale_list,
    name='sale_list'
    ),

    path(
    'products/',
    views.product_list,
    name='product_list'
    ),

    path(
    'products/cashier/',
    views.cashier_product_list,
    name='cashier_product_list'
    ),

    path(
    'sales/<int:sale_id>/',
    views.sale_detail,
    name='sale_detail'
    ),

    path(
    'sales/<int:sale_id>/payment/',
    views.payment_create,
    name='payment_create'
    ),

    path(
    'payments/',
    views.payment_list,
    name='payment_list',
    ),

    path(
    'payment-history/',
    views.payment_history,
    name='payment_history',
    ),

   path(
    'outstanding-payments/',
    views.outstanding_payments,
    name='outstanding_payments',
    ),

    path(
    'special-orders/',
    views.special_order_list,
    name='special_order_list'
    ),

    path(
        'special-orders/new/',
        views.special_order_create,
        name='special_order_create'
    ),

    path(
    'production/special-orders/',
    views.production_special_order_list,
    name='production_special_order_list'
    ),

    path(
    'special-orders/<int:special_order_id>/confirm/',
    views.special_order_confirm,
    name='special_order_confirm'
    ),

    path(
    'special-orders/<int:special_order_id>/start-production/',
    views.special_order_start_production,
    name='special_order_start_production'
    ),

    path(
    'special-orders/<int:special_order_id>/mark-ready/',
    views.special_order_mark_ready,
    name='special_order_mark_ready'
    ),

    path(
    'special-orders/<int:special_order_id>/complete/',
    views.special_order_complete,
    name='special_order_complete'
    ),

    
    path(
        'special-orders/<int:special_order_id>/',
        views.special_order_detail,
        name='special_order_detail'
    ),

    path(
    'recipes/',
    views.recipe_list,
    name='recipe_list'
    ),

    path(
    'recipes/new/',
    views.recipe_create,
    name='recipe_create'
    ),

    path(
    'recipes/product/<int:product_id>/ingredients/',
    views.recipe_product_ingredients,
    name='recipe_product_ingredients'
    ),

    path(
    'recipes/<int:recipe_id>/edit/',
    views.recipe_edit,
    name='recipe_edit'
    ),  

    path(
    'recipes/<int:recipe_id>/',
    views.recipe_detail,
    name='recipe_detail'
    ),

    path(
    'reports/',
    views.owner_reports,
    name='owner_reports'
    ),
    path(
    'reports/sales/',
    views.owner_sales_report,
    name='owner_sales_report'
    ),

    path(
    'reports/sales/csv/',
    views.owner_sales_report_csv,
    name='owner_sales_report_csv'
    ),

    path(
    'reports/sales/excel/',
    views.owner_sales_report_excel,
    name='owner_sales_report_excel'
    ),

    path(
    'reports/sales/pdf/',
    views.owner_sales_report_pdf,
    name='owner_sales_report_pdf'
    ),

    path(
    'reports/payments/',
    views.owner_payment_report,
    name='owner_payment_report'
    ),

    path(
    'reports/payments/csv/',
    views.owner_payment_report_csv,
    name='owner_payment_report_csv'
    ),

    path(
    'reports/payments/excel/',
    views.owner_payment_report_excel,
    name='owner_payment_report_excel'
    ),

    path(
    'reports/payments/pdf/',
    views.owner_payment_report_pdf,
    name='owner_payment_report_pdf'
    ),

    path(
    'reports/production/',
    views.owner_production_report,
    name='owner_production_report'
    ),

    path(
    'reports/production/csv/',
    views.owner_production_report_csv,
    name='owner_production_report_csv'
    ),

    path(
    'reports/production/excel/',
    views.owner_production_report_excel,
    name='owner_production_report_excel'
    ),

    path(
    'reports/production/pdf/',
    views.owner_production_report_pdf,
    name='owner_production_report_pdf'
    ),

    path(
    'reports/stock/',
    views.owner_stock_report,
    name='owner_stock_report'
    ),

    path(
    'reports/stock/csv/',
    views.owner_stock_report_csv,
    name='owner_stock_report_csv'
    ),

    path(
        'reports/stock/excel/',
        views.owner_stock_report_excel,
        name='owner_stock_report_excel'
    ),

    path(
        'reports/stock/pdf/',
        views.owner_stock_report_pdf,
        name='owner_stock_report_pdf'
    ),

    path(
    'reports/special-orders/',
    views.owner_special_order_report,
    name='owner_special_order_report'
    ),

    path(
    'reports/special-orders/csv/',
    views.owner_special_order_report_csv,
    name='owner_special_order_report_csv'
    ),

    path(
        'reports/special-orders/excel/',
        views.owner_special_order_report_excel,
        name='owner_special_order_report_excel'
    ),

    path(
        'reports/special-orders/pdf/',
        views.owner_special_order_report_pdf,
        name='owner_special_order_report_pdf'
    ),

    path(
    'reports/business-summary/',
    views.owner_business_summary,
    name='owner_business_summary'
    ),

    path(
    'reports/business-summary/pdf/',
    views.owner_business_summary_pdf,
    name='owner_business_summary_pdf'
    ),

    path(
    'reports/business-summary/csv/',
    views.owner_business_summary_csv,
    name='owner_business_summary_csv'
    ),

    path(
    'reports/business-summary/excel/',
    views.owner_business_summary_excel,
    name='owner_business_summary_excel'
    ),

    path(
    'ingredients/',
    views.ingredient_list,
    name='ingredient_list'
    ),

    path(
        'ingredients/new/',
        views.ingredient_create,
        name='ingredient_create'
    ),

    path(
    "ingredients/<int:pk>/edit/",
    views.ingredient_edit,
    name="ingredient_edit",
    ),

    path(
    "ingredients/stock-movement/new/",
    views.stock_movement_create,
    name="stock_movement_create",
    ),

    path(
    "ingredients/stock-movements/",
    views.stock_movement_list,
    name="stock_movement_list",
    ),

    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]