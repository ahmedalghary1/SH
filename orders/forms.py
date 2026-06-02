from django import forms

from inventory.models import Warehouse

from .models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            'order_type', 'customer', 'warehouse', 'payment_method',
            'payment_status', 'paid_amount', 'discount', 'notes',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse'].queryset = Warehouse.objects.filter(is_active=True)
