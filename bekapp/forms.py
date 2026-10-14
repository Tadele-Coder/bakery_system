
from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model

from .models import (
    Product,
    Payment,
    Production,
    ProductionItem,
    Customer,
    SpecialOrder,
    Recipe,
    RecipeIngredient,
    Ingredient,
    StockMovement,
    BusinessSettings,
)


class ProductForm(forms.ModelForm):

    class Meta:
        model = Product
        fields = [
            'name',
            'category',
            'description',
            'price',
            'is_available',
        ]

        widgets = {
            'name': forms.TextInput(
                attrs={
                    'placeholder': 'Enter product name',
                }
            ),
            'category': forms.Select(),
            'description': forms.Textarea(
                attrs={
                    'placeholder': 'Enter product description',
                    'rows': 4,
                }
            ),
            'price': forms.NumberInput(
                attrs={
                    'placeholder': 'Enter product price',
                    'step': '0.01',
                    'min': '0',
                }
            ),
            'is_available': forms.CheckboxInput(),
        }


class SaleItemForm(forms.Form):

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(
            is_available=True
        ).order_by('name'),
        empty_label="Select Product",
        widget=forms.Select(
            attrs={
                'class': 'form-select',
            }
        ),
    )

    quantity = forms.DecimalField(
        min_value=1,
        max_digits=10,
        decimal_places=0,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1',
                'placeholder': 'Enter quantity',
            }
        ),
    )


class PaymentForm(forms.Form):

    method = forms.ChoiceField(
        choices=Payment.Method.choices,
        widget=forms.Select(
            attrs={
                'class': 'form-select',
            }
        ),
    )

    amount = forms.DecimalField(
        min_value=0.01,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'min': '0.01',
                'step': '0.01',
                'placeholder': 'Enter payment amount',
            }
        ),
    )

    reference_number = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Reference number (optional)',
            }
        ),
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Payment notes (optional)',
            }
        ),
    )


class CustomerForm(forms.ModelForm):

    class Meta:
        model = Customer
        fields = [
            'name',
            'phone',
            'email',
            'address',
            'notes',
        ]

        widgets = {
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Customer name',
                }
            ),
            'phone': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Phone number',
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Email address',
                }
            ),
            'address': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 2,
                    'placeholder': 'Customer address',
                }
            ),
            'notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 2,
                    'placeholder': 'Additional notes',
                }
            ),
        }


class SpecialOrderForm(forms.ModelForm):

    deposit_amount = forms.DecimalField(
        required=False,
        initial=0,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Enter deposit amount',
            }
        ),
    )

    deposit_method = forms.ChoiceField(
        required=False,
        choices=Payment.Method.choices,
        initial=Payment.Method.CASH,
        widget=forms.Select(
            attrs={
                'class': 'form-select',
            }
        ),
    )

    deposit_reference_number = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Reference number (optional)',
            }
        ),
    )

    class Meta:
        model = SpecialOrder
        fields = [
            'event_type',
            'event_date',
            'pickup_time',
            'deposit_amount',
            'notes',
        ]

        widgets = {
            'event_type': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'event_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'pickup_time': forms.TimeInput(
                attrs={
                    'class': 'form-control',
                    'type': 'time',
                }
            ),
            'notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Special instructions or notes',
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        deposit_amount = (
            cleaned_data.get('deposit_amount') or 0
        )
        deposit_method = cleaned_data.get('deposit_method')

        if deposit_amount > 0 and not deposit_method:
            self.add_error(
                'deposit_method',
                'Please select a payment method for the deposit.',
            )

        return cleaned_data


class SpecialOrderItemForm(forms.Form):

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(
            is_available=True
        ).order_by('name'),
        empty_label="Select Product",
        widget=forms.Select(
            attrs={
                'class': 'form-select special-order-product',
            }
        ),
    )

    quantity = forms.DecimalField(
        min_value=0.01,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control special-order-quantity',
                'min': '0.01',
                'step': '0.01',
                'placeholder': 'Enter quantity',
            }
        ),
    )

    customization = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control special-order-customization',
                'rows': 2,
                'placeholder': (
                    'Design, flavor, size, decoration, message, etc.'
                ),
            }
        ),
    )


class RecipeForm(forms.ModelForm):

    class Meta:
        model = Recipe
        fields = [
            'product',
            'description',
        ]

        widgets = {
            'product': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 4,
                    'placeholder': (
                        'Enter recipe instructions or description...'
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['product'].queryset = Product.objects.filter(
            is_available=True
        ).order_by('name')

        self.fields['product'].empty_label = "Select Product"


class RecipeIngredientForm(forms.Form):

    ingredient = forms.ModelChoiceField(
        queryset=Ingredient.objects.filter(
            is_active=True
        ).order_by('name'),
        empty_label="Select Ingredient",
        widget=forms.Select(
            attrs={
                'class': 'form-select recipe-ingredient',
            }
        ),
    )

    quantity = forms.DecimalField(
        min_value=0.001,
        max_digits=10,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control recipe-quantity',
                'min': '0.001',
                'step': '0.001',
                'placeholder': 'Enter quantity',
            }
        ),
    )


User = get_user_model()


class StaffCreateForm(forms.ModelForm):

    password = forms.CharField(
        widget=forms.PasswordInput,
        label="Password",
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm Password",
    )

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'role',
            'password',
        ]

        widgets = {
            'username': forms.TextInput(
                attrs={
                    'placeholder': 'Enter username',
                }
            ),
            'first_name': forms.TextInput(
                attrs={
                    'placeholder': 'Enter first name',
                }
            ),
            'last_name': forms.TextInput(
                attrs={
                    'placeholder': 'Enter last name',
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'placeholder': 'Enter email address',
                }
            ),
            'role': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['role'].choices = [
            (
                User.Role.CASHIER,
                User.Role.CASHIER.label,
            ),
            (
                User.Role.PRODUCTION_MANAGER,
                User.Role.PRODUCTION_MANAGER.label,
            ),
        ]

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error(
                    'confirm_password',
                    'Passwords do not match.',
                )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)

        user.set_password(
            self.cleaned_data['password']
        )

        user.is_active = True

        if commit:
            user.save()

        return user


class StaffEditForm(forms.ModelForm):

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'role',
            'is_active',
        ]

        widgets = {
            'username': forms.TextInput(
                attrs={
                    'placeholder': 'Enter username',
                }
            ),
            'first_name': forms.TextInput(
                attrs={
                    'placeholder': 'Enter first name',
                }
            ),
            'last_name': forms.TextInput(
                attrs={
                    'placeholder': 'Enter last name',
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'placeholder': 'Enter email address',
                }
            ),
            'role': forms.Select(),
            'is_active': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['role'].choices = [
            (
                User.Role.CASHIER,
                User.Role.CASHIER.label,
            ),
            (
                User.Role.PRODUCTION_MANAGER,
                User.Role.PRODUCTION_MANAGER.label,
            ),
        ]


class IngredientForm(forms.ModelForm):

    class Meta:
        model = Ingredient
        fields = [
            'name',
            'unit',
            'current_stock',
            'minimum_stock',
            'cost_per_unit',
            'is_active',
        ]

        widgets = {
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter ingredient name',
                }
            ),
            'unit': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'current_stock': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.001',
                    'min': '0',
                    'placeholder': 'Enter current stock',
                }
            ),
            'minimum_stock': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.001',
                    'min': '0',
                    'placeholder': 'Enter minimum stock',
                }
            ),
            'cost_per_unit': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': 'Enter cost per unit',
                }
            ),
            'is_active': forms.CheckboxInput(
                attrs={
                    'class': 'form-check-input',
                }
            ),
        }


class StockMovementForm(forms.ModelForm):

    class Meta:
        model = StockMovement
        fields = [
            'ingredient',
            'movement_type',
            'quantity',
            'note',
        ]

        widgets = {
            'ingredient': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'movement_type': forms.Select(
                attrs={
                    'class': 'form-select',
                }
            ),
            'quantity': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.001',
                    'min': '0.001',
                    'placeholder': 'Enter quantity',
                }
            ),
            'note': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Optional note',
                }
            ),
        }


class BusinessSettingsForm(forms.ModelForm):

    class Meta:
        model = BusinessSettings
        fields = [
            'business_name',
            'phone',
            'email',
            'address',
            'logo',
        ]

        widgets = {
            'business_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter bakery name',
                }
            ),
            'phone': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter phone number',
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter email address',
                }
            ),
            'address': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Enter bakery address',
                }
            ),
            'logo': forms.ClearableFileInput(
                attrs={
                    'class': 'form-control',
                }
            ),
        }
