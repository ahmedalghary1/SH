from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, role_required
from config.search import arabic_search_q
from inventory.models import Stock, StockBatch, Warehouse
from inventory.models import StockMovement
from inventory.services import adjust_stock, stock_in, transfer_stock
from orders.models import Order, OrderItem

from .forms import BulkPriceUpdateForm, CategoryForm, ColorForm, InitialProductVariantForm, InitialStockForm, ProductForm, ProductVariantForm, SizeForm
from .models import Category, Color, Product, ProductVariant, Size


def generate_variant_sku(product, color_id=None, size_id=None, current_pk=None):
    base = f'{product.sku}-{color_id or "0"}-{size_id or "0"}'
    sku = base
    counter = 2
    qs = ProductVariant.objects.filter(variant_sku=sku)
    if current_pk:
        qs = qs.exclude(pk=current_pk)
    while qs.exists():
        sku = f'{base}-{counter}'
        qs = ProductVariant.objects.filter(variant_sku=sku)
        if current_pk:
            qs = qs.exclude(pk=current_pk)
        counter += 1
    return sku


class ProductListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Product
    template_name = 'products/list.html'
    context_object_name = 'products'
    paginate_by = 20

    def get_queryset(self):
        qs = Product.objects.select_related('category').prefetch_related('variants').annotate(
            variant_count=Count('variants', distinct=True),
            total_quantity=Sum('variants__stock__quantity'),
        )
        q = self.request.GET.get('q')
        category = self.request.GET.get('category')
        status = self.request.GET.get('status')
        if q:
            qs = qs.filter(arabic_search_q(('name', 'sku'), q))
        if category:
            qs = qs.filter(category_id=category)
        if status in {'active', 'inactive'}:
            qs = qs.filter(is_active=(status == 'active'))
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.filter(is_active=True)
        return context


class ProductDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Product
    template_name = 'products/detail.html'
    context_object_name = 'product'

    def get_queryset(self):
        return Product.objects.select_related('category').prefetch_related('variants__color', 'variants__size')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        variants = self.object.variants.all()
        stocks = Stock.objects.filter(variant__product=self.object).select_related('warehouse', 'variant__color', 'variant__size')
        order_items = OrderItem.objects.filter(variant__product=self.object).exclude(
            order__status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
        ).select_related('order__customer', 'order__created_by', 'variant__color', 'variant__size').order_by('-order__created_at')
        movements = StockMovement.objects.filter(variant__product=self.object).select_related(
            'variant__color', 'variant__size', 'from_warehouse', 'to_warehouse', 'created_by',
        ).order_by('-created_at')[:100]
        context['stock_rows'] = stocks
        context['movement_rows'] = movements
        context['sold_quantity'] = order_items.aggregate(total=Sum('quantity'))['total'] or 0
        context['sales_count'] = order_items.values('order_id').distinct().count()
        context['product_sales_total'] = order_items.aggregate(total=Sum('total'))['total'] or 0
        context['product_profit_total'] = order_items.aggregate(total=Sum('profit_total'))['total'] or 0
        context['order_items'] = order_items[:50]
        context['current_quantity'] = stocks.aggregate(total=Sum('quantity'))['total'] or 0
        context['variants'] = variants
        return context


class ProductMovementReportView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Product
    template_name = 'products/movement_report.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        variant_id = self.request.GET.get('variant')
        day = parse_date(self.request.GET.get('day') or '')
        date_from = parse_date(self.request.GET.get('date_from') or '')
        date_to = parse_date(self.request.GET.get('date_to') or '')

        variants = self.object.variants.select_related('color', 'size')
        movements = StockMovement.objects.filter(variant__product=self.object).select_related(
            'variant__color', 'variant__size', 'from_warehouse', 'to_warehouse', 'created_by', 'batch',
        )
        order_items = OrderItem.objects.filter(variant__product=self.object).select_related(
            'order__customer', 'order__created_by', 'variant__color', 'variant__size', 'warehouse', 'stock_batch',
        )
        batches = StockBatch.objects.filter(variant__product=self.object, remaining_quantity__gt=0).select_related(
            'variant__color', 'variant__size', 'warehouse',
        )
        if variant_id:
            movements = movements.filter(variant_id=variant_id)
            order_items = order_items.filter(variant_id=variant_id)
            batches = batches.filter(variant_id=variant_id)
        if day:
            movements = movements.filter(created_at__date=day)
            order_items = order_items.filter(order__created_at__date=day)
        else:
            if date_from:
                movements = movements.filter(created_at__date__gte=date_from)
                order_items = order_items.filter(order__created_at__date__gte=date_from)
            if date_to:
                movements = movements.filter(created_at__date__lte=date_to)
                order_items = order_items.filter(order__created_at__date__lte=date_to)

        context.update({
            'variants': variants,
            'selected_variant_id': variant_id or '',
            'day': self.request.GET.get('day', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'movement_rows': movements.order_by('-created_at')[:300],
            'order_items': order_items.order_by('-order__created_at')[:300],
            'stock_rows': Stock.objects.filter(variant__product=self.object).select_related('variant__color', 'variant__size', 'warehouse'),
            'batch_rows': batches.order_by('received_at', 'pk'),
        })
        return context


class ProductCreateView(ManagerRequiredMixin, View):
    template_name = 'products/create.html'

    def get(self, request):
        return render(request, self.template_name, {
            'product_form': ProductForm(),
            'variant_form': InitialProductVariantForm(),
            'stock_form': InitialStockForm(),
            'product_names': Product.objects.filter(is_active=True).order_by('name').values_list('name', flat=True).distinct()[:200],
        })

    def post(self, request):
        product_form = ProductForm(request.POST, request.FILES)
        variant_form = InitialProductVariantForm(request.POST)
        stock_form = InitialStockForm(request.POST)
        if product_form.is_valid() and variant_form.is_valid() and stock_form.is_valid():
            with transaction.atomic():
                product = product_form.save()
                variant = None
                if variant_form.has_variant_data() or stock_form.has_stock_data():
                    variant = variant_form.save(commit=False)
                    variant.product = product
                    if not variant.variant_sku:
                        variant.variant_sku = generate_variant_sku(product, variant.color_id, variant.size_id)
                    variant.save()
                if stock_form.has_stock_data() and variant:
                    warehouse = stock_form.cleaned_data['warehouse']
                    quantity = stock_form.cleaned_data.get('quantity') or 0
                    if quantity > 0:
                        stock_in(
                            variant=variant,
                            warehouse=warehouse,
                            quantity=quantity,
                            user=request.user,
                            note='كمية أولية عند إضافة المنتج',
                        )
                    stock, _ = Stock.objects.get_or_create(
                        warehouse=warehouse,
                        variant=variant,
                        defaults={'quantity': 0},
                    )
                    stock.min_quantity = 0
                    stock.save(update_fields=['min_quantity'])
            messages.success(request, 'تم إضافة المنتج')
            return redirect('products:detail', pk=product.pk)
        return render(request, self.template_name, {
            'product_form': product_form,
            'variant_form': variant_form,
            'stock_form': stock_form,
            'product_names': Product.objects.filter(is_active=True).order_by('name').values_list('name', flat=True).distinct()[:200],
        })


class ProductUpdateView(ManagerRequiredMixin, View):
    template_name = 'products/update.html'

    def get_product(self):
        return get_object_or_404(Product.objects.select_related('category'), pk=self.kwargs['pk'])

    def get_stock_rows(self, product):
        return Stock.objects.select_related('warehouse', 'variant__color', 'variant__size', 'variant__product').filter(
            variant__product=product
        ).order_by('variant__variant_sku', 'warehouse__name')

    def get(self, request, pk):
        product = self.get_product()
        return render(request, self.template_name, {
            'product': product,
            'form': ProductForm(instance=product),
            'stock_rows': self.get_stock_rows(product),
            'warehouses': Warehouse.objects.filter(is_active=True).order_by('warehouse_type', 'name'),
        })

    def post(self, request, pk):
        product = self.get_product()
        form = ProductForm(request.POST, request.FILES, instance=product)
        stock_rows = self.get_stock_rows(product)
        warehouses = Warehouse.objects.filter(is_active=True).order_by('warehouse_type', 'name')
        if form.is_valid():
            try:
                with transaction.atomic():
                    product = form.save()
                    self.update_stock_rows(request, product)
                messages.success(request, 'تم تحديث المنتج والمخزون')
                return redirect('products:detail', pk=product.pk)
            except (ValidationError, ValueError) as exc:
                message = exc.message if hasattr(exc, 'message') else str(exc)
                form.add_error(None, message)
        return render(request, self.template_name, {
            'product': product,
            'form': form,
            'stock_rows': stock_rows,
            'warehouses': warehouses,
        })

    def update_stock_rows(self, request, product):
        stock_ids = request.POST.getlist('stock_id')
        for stock_id in stock_ids:
            stock = Stock.objects.select_for_update().select_related('warehouse', 'variant').get(
                pk=stock_id,
                variant__product=product,
            )
            warehouse_id = request.POST.get(f'stock_{stock_id}_warehouse')
            quantity = int(request.POST.get(f'stock_{stock_id}_quantity') or 0)
            min_quantity = int(request.POST.get(f'stock_{stock_id}_min_quantity') or 0)
            if quantity < 0 or min_quantity < 0:
                raise ValidationError('لا يمكن أن تكون كميات المخزون سالبة')
            target_warehouse = get_object_or_404(Warehouse, pk=warehouse_id, is_active=True)
            if target_warehouse != stock.warehouse and stock.quantity > 0:
                variant = stock.variant
                transfer_stock(
                    variant=variant,
                    from_warehouse=stock.warehouse,
                    to_warehouse=target_warehouse,
                    quantity=stock.quantity,
                    user=request.user,
                    note=f'نقل مخزون المنتج {product.sku} أثناء تعديل المنتج',
                )
                stock.delete()
                stock, _ = Stock.objects.select_for_update().get_or_create(
                    warehouse=target_warehouse,
                    variant=variant,
                    defaults={'quantity': 0},
                )
            elif target_warehouse != stock.warehouse:
                existing = Stock.objects.select_for_update().filter(
                    warehouse=target_warehouse,
                    variant=stock.variant,
                ).exclude(pk=stock.pk).first()
                if existing:
                    stock.delete()
                    stock = existing
                else:
                    stock.warehouse = target_warehouse
                    stock.save(update_fields=['warehouse'])
            if stock.quantity != quantity:
                adjust_stock(
                    variant=stock.variant,
                    warehouse=stock.warehouse,
                    new_quantity=quantity,
                    user=request.user,
                    note=f'تعديل كمية المنتج {product.sku}',
                )
                stock.refresh_from_db()
            stock.min_quantity = min_quantity
            stock.save(update_fields=['min_quantity'])


class ProductDeactivateView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = False
        product.save(update_fields=['is_active'])
        messages.success(request, 'تم إيقاف المنتج')
        return redirect('products:list')


class BulkPriceUpdateView(ManagerRequiredMixin, FormView):
    template_name = 'products/bulk_price_update.html'
    form_class = BulkPriceUpdateForm
    success_url = reverse_lazy('products:list')

    def form_valid(self, form):
        qs = ProductVariant.objects.select_related('product')
        if not form.cleaned_data.get('include_inactive'):
            qs = qs.filter(is_active=True, product__is_active=True)
        category = form.cleaned_data.get('category')
        if category:
            qs = qs.filter(product__category=category)
        mode = form.cleaned_data['mode']
        sale_value = form.cleaned_data.get('sale_price')
        cost_value = form.cleaned_data.get('cost_price')
        count = 0
        with transaction.atomic():
            for variant in qs.select_for_update():
                update_fields = []
                if sale_value is not None:
                    if mode == BulkPriceUpdateForm.MODE_PERCENT:
                        variant.sale_price = max(variant.sale_price + (variant.sale_price * sale_value / 100), 0)
                    else:
                        variant.sale_price = max(sale_value, 0)
                    update_fields.append('sale_price')
                if cost_value is not None:
                    if mode == BulkPriceUpdateForm.MODE_PERCENT:
                        variant.cost_price = max(variant.cost_price + (variant.cost_price * cost_value / 100), 0)
                    else:
                        variant.cost_price = max(cost_value, 0)
                    update_fields.append('cost_price')
                if update_fields:
                    variant.save(update_fields=update_fields)
                    count += 1
        messages.success(self.request, f'تم تحديث أسعار {count} لون/مقاس')
        return super().form_valid(form)


class CategoryListView(ManagerRequiredMixin, ListView):
    model = Category
    template_name = 'products/catalog/categories.html'
    context_object_name = 'categories'
    paginate_by = 20

    def get_queryset(self):
        return Category.objects.select_related('parent').order_by('name')


class CategoryCreateView(ManagerRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'products/catalog/category_form.html'
    success_url = reverse_lazy('products:categories')

    def form_valid(self, form):
        messages.success(self.request, 'تم إضافة التصنيف')
        return super().form_valid(form)


class CategoryUpdateView(ManagerRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'products/catalog/category_form.html'
    success_url = reverse_lazy('products:categories')

    def form_valid(self, form):
        messages.success(self.request, 'تم تحديث التصنيف')
        return super().form_valid(form)


class ColorListView(ManagerRequiredMixin, ListView):
    model = Color
    template_name = 'products/catalog/colors.html'
    context_object_name = 'colors'
    paginate_by = 20
    ordering = ('name',)


class ColorCreateView(ManagerRequiredMixin, CreateView):
    model = Color
    form_class = ColorForm
    template_name = 'products/catalog/color_form.html'
    success_url = reverse_lazy('products:colors')

    def form_valid(self, form):
        messages.success(self.request, 'تم إضافة اللون')
        return super().form_valid(form)


class ColorUpdateView(ManagerRequiredMixin, UpdateView):
    model = Color
    form_class = ColorForm
    template_name = 'products/catalog/color_form.html'
    success_url = reverse_lazy('products:colors')

    def form_valid(self, form):
        messages.success(self.request, 'تم تحديث اللون')
        return super().form_valid(form)


class SizeListView(ManagerRequiredMixin, ListView):
    model = Size
    template_name = 'products/catalog/sizes.html'
    context_object_name = 'sizes'
    paginate_by = 20


class SizeCreateView(ManagerRequiredMixin, CreateView):
    model = Size
    form_class = SizeForm
    template_name = 'products/catalog/size_form.html'
    success_url = reverse_lazy('products:sizes')

    def form_valid(self, form):
        messages.success(self.request, 'تم إضافة المقاس')
        return super().form_valid(form)


class SizeUpdateView(ManagerRequiredMixin, UpdateView):
    model = Size
    form_class = SizeForm
    template_name = 'products/catalog/size_form.html'
    success_url = reverse_lazy('products:sizes')

    def form_valid(self, form):
        messages.success(self.request, 'تم تحديث المقاس')
        return super().form_valid(form)


class ProductVariantCreateView(ManagerRequiredMixin, CreateView):
    model = ProductVariant
    form_class = ProductVariantForm
    template_name = 'products/variant_form.html'

    def get_initial(self):
        initial = super().get_initial()
        product_id = self.request.GET.get('product')
        if product_id:
            initial['product'] = product_id
        return initial

    def get_success_url(self):
        return reverse_lazy('products:detail', kwargs={'pk': self.object.product_id})

    def form_valid(self, form):
        if not form.instance.variant_sku:
            form.instance.variant_sku = generate_variant_sku(
                form.instance.product,
                form.instance.color_id,
                form.instance.size_id,
            )
        messages.success(self.request, 'تم إضافة اللون والمقاس')
        return super().form_valid(form)


class ProductVariantUpdateView(ManagerRequiredMixin, UpdateView):
    model = ProductVariant
    form_class = ProductVariantForm
    template_name = 'products/variant_form.html'

    def get_success_url(self):
        return reverse_lazy('products:detail', kwargs={'pk': self.object.product_id})

    def form_valid(self, form):
        form.instance.variant_sku = form.instance.variant_sku or generate_variant_sku(
            form.instance.product,
            form.instance.color_id,
            form.instance.size_id,
            current_pk=form.instance.pk,
        )
        messages.success(self.request, 'تم تحديث اللون والمقاس')
        return super().form_valid(form)


class ProductVariantDeactivateView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        variant = get_object_or_404(ProductVariant, pk=pk)
        variant.is_active = False
        variant.save(update_fields=['is_active'])
        messages.success(request, 'تم إيقاف اللون والمقاس')
        return redirect('products:detail', pk=variant.product_id)


@require_GET
@role_required('manager', 'sales', 'warehouse')
def ajax_search_products(request):
    q = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True)
    if q:
        products = products.filter(arabic_search_q(('name', 'sku', 'variants__variant_sku'), q)).distinct()
    data = [
        {'id': p.id, 'name': p.name, 'sku': p.sku}
        for p in products[:12]
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب المنتجات', 'data': data})


@require_GET
@role_required('manager', 'sales', 'warehouse')
def ajax_get_product_variants(request, product_id):
    variants = ProductVariant.objects.filter(product_id=product_id, is_active=True).select_related('color', 'size')
    data = [
        {
            'id': v.id,
            'variant_sku': v.variant_sku,
            'color': v.color.name if v.color else '',
            'size': v.size.name if v.size else '',
        }
        for v in variants
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب الألوان والمقاسات', 'data': data})


@require_GET
@role_required('manager', 'sales', 'warehouse')
def ajax_get_variant_price(request, variant_id):
    order_type = request.GET.get('order_type', 'b2c')
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id, is_active=True)
    price = variant.sale_price
    return JsonResponse({'success': True, 'message': 'تم جلب السعر', 'data': {'price': str(price)}})


@require_GET
@role_required('manager', 'sales', 'warehouse')
def api_categories(request):
    categories = Category.objects.filter(is_active=True).select_related('parent').order_by('name')
    data = [
        {
            'id': category.id,
            'name': category.name,
            'parent_id': category.parent_id,
        }
        for category in categories
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب الأقسام', 'data': data})


@require_GET
@role_required('manager', 'sales', 'warehouse')
def api_products(request):
    qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants__color', 'variants__size')
    q = request.GET.get('q')
    category = request.GET.get('category')
    color = request.GET.get('color')
    size = request.GET.get('size')
    warehouse = request.GET.get('warehouse')
    if q:
        qs = qs.filter(arabic_search_q(('name', 'sku', 'variants__variant_sku'), q)).distinct()
    if category:
        qs = qs.filter(category_id=category)
    if color:
        qs = qs.filter(variants__color_id=color).distinct()
    if size:
        qs = qs.filter(variants__size_id=size).distinct()

    warehouse_obj = None
    if warehouse:
        warehouse_obj = Warehouse.objects.filter(pk=warehouse, is_active=True).first()

    data = []
    for product in qs[:100]:
        variants = []
        for variant in product.variants.all():
            stock_qs = Stock.objects.filter(variant=variant)
            if warehouse_obj:
                stock_qs = stock_qs.filter(warehouse=warehouse_obj)
            quantity = sum(stock.quantity for stock in stock_qs)
            variants.append({
                'id': variant.id,
                'code': variant.variant_sku,
                'barcode': variant.barcode or '',
                'color': variant.color.name if variant.color else '',
                'size': variant.size.name if variant.size else '',
                'sale_price': str(variant.sale_price),
                'quantity': quantity,
                'is_active': variant.is_active,
            })
        data.append({
            'id': product.id,
            'name': product.name,
            'code': product.sku,
            'category': product.category.name if product.category else '',
            'image': product.image.url if product.image else '',
            'variants': variants,
        })
    return JsonResponse({'success': True, 'message': 'تم جلب المنتجات', 'data': data})

# Create your views here.
