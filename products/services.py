from django.core.exceptions import ValidationError
from django.db import transaction
from inventory.models import Stock
from sales_reps.services import get_or_create_sales_rep_warehouse
from .models import Product, ProductVariant, Color, Size


@transaction.atomic
def create_representative_product(*, data, user):
    if user.role != 'sales' or not user.is_active:
        raise ValidationError('هذه العملية مخصصة للمندوب.')
    from accounts.models import Branch
    Branch.objects.select_for_update().get(pk=user.branch_id)
    from .forms import RepresentativeProductForm
    form = RepresentativeProductForm(data)
    if not form.is_valid():
        raise ValidationError('؛ '.join(str(error) for errors in form.errors.values() for error in errors))
    values = form.cleaned_data
    warehouse = get_or_create_sales_rep_warehouse(user)
    product = Product.objects.create(
        branch_id=user.branch_id, name=values['name'], sku=values['sku'],
        retail_price=values['retail_price'], wholesale_price=values['wholesale_price'])
    color = Color.objects.get_or_create(name=values['color_name'])[0] if values['color_name'] else None
    size = Size.objects.get_or_create(name=values['size_name'])[0] if values['size_name'] else None
    variant_sku = values['sku'] + '-REP'
    suffix = 1
    while ProductVariant.objects.filter(variant_sku=variant_sku).exists():
        suffix += 1
        variant_sku = f"{values['sku']}-REP-{suffix}"
    variant = ProductVariant.objects.create(
        branch_id=user.branch_id, product=product, variant_sku=variant_sku, color=color, size=size,
        cost_price=values['cost_price'] or 0, retail_price=values['retail_price'],
        wholesale_price=values['wholesale_price'], sale_price=values['retail_price'])
    Stock.objects.create(warehouse=warehouse, variant=variant, quantity=0)
    return product, variant
