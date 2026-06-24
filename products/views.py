from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, can_view_costs, role_required
from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin
from config.search import arabic_search_q
from inventory.models import Stock, StockBatch, Warehouse
from inventory.models import StockMovement
from inventory.services import adjust_stock, stock_in, transfer_stock
from orders.models import Order, OrderItem

from .forms import CategoryForm, ColorForm, InitialProductVariantForm, InitialStockForm, ProductForm, ProductVariantForm, SizeForm
from .models import Category, Color, Product, ProductVariant, Size


def generate_variant_sku(product, color_id=None, size_id=None, current_pk=None):
    base = f'{product.sku}-{color_id or "0"}-{size_id or "0"}'
    sku = base
    counter = 2
    existing = set(
        ProductVariant.objects.filter(variant_sku__startswith=base)
        .values_list('variant_sku', flat=True)
    )
    if current_pk:
        existing = {s for s in existing if s != ProductVariant.objects.filter(pk=current_pk).values_list('variant_sku', flat=True).first()}
    while sku in existing:
        sku = f'{base}-{counter}'
        counter += 1
    return sku


class ProductListView(RoleRequiredMixin, ExportListMixin, ListView):
    allowed_roles = ('manager', 'warehouse')
    model = Product
    template_name = 'products/list.html'
    context_object_name = 'products'
    paginate_by = 20
    export_title = 'قائمة المنتجات'
    export_filename = 'products'
    export_columns = (
        ('اسم المنتج', 'name'),
        ('كود المنتج', 'sku'),
        ('التصنيف', 'category'),
        ('الخامة', 'material'),
        ('عدد القطع في الدستة', 'pieces_per_dozen'),
        ('عدد الألوان/المقاسات', 'variant_count'),
        ('الكمية المتاحة', 'total_quantity'),
        ('الحالة', lambda product: 'نشط' if product.is_active else 'متوقف'),
    )

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
    allowed_roles = ('manager', 'warehouse')
    model = Product
    template_name = 'products/detail.html'
    context_object_name = 'product'

    def get_queryset(self):
        return Product.objects.select_related('category').prefetch_related('variants__color', 'variants__size')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
        variants = self.object.variants.all()
        stocks = Stock.objects.filter(variant__product=self.object).select_related('warehouse', 'variant__color', 'variant__size')
        order_items = OrderItem.objects.filter(variant__product=self.object).exclude(
            order__status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED],
        ).select_related('order__customer', 'order__created_by', 'variant__color', 'variant__size').order_by('-order__created_at')
        movements = StockMovement.objects.filter(variant__product=self.object).select_related(
            'variant__color', 'variant__size', 'from_warehouse', 'to_warehouse', 'created_by',
        ).order_by('-created_at')[:100]
        agg = order_items.aggregate(
            sold_quantity=Sum('quantity'),
            product_sales_total=Sum('total'),
            product_profit_total=Sum('profit_total'),
        )
        stock_agg = stocks.aggregate(current_quantity=Sum('quantity'))
        context['stock_rows'] = stocks
        context['movement_rows'] = movements
        context['sold_quantity'] = agg['sold_quantity'] or 0
        context['sales_count'] = order_items.values('order_id').distinct().count()
        context['product_sales_total'] = agg['product_sales_total'] or 0
        context['product_profit_total'] = agg['product_profit_total'] or 0
        context['order_items'] = order_items[:50]
        context['current_quantity'] = stock_agg['current_quantity'] or 0
        context['variants'] = variants
        return context


class ProductMovementReportView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Product
    template_name = 'products/movement_report.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_view_costs'] = can_view_costs(self.request.user)
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
            'can_view_costs': can_view_costs(request.user),
        })

    def post(self, request):
        product_form = ProductForm(request.POST, request.FILES)
        variant_form = InitialProductVariantForm(request.POST, request.FILES)
        stock_form = InitialStockForm(request.POST)
        if product_form.is_valid() and variant_form.is_valid() and stock_form.is_valid():
            with transaction.atomic():
                product = product_form.save()
                variant = None
                if variant_form.has_variant_data() or stock_form.has_stock_data():
                    variant = variant_form.save(commit=False)
                    variant.product = product
                    if not variant.color_id:
                        color_name = (variant_form.cleaned_data.get('new_color_name') or '').strip()
                        variant.color, _ = Color.objects.get_or_create(name=color_name)
                    if not variant.size_id:
                        size_name = (variant_form.cleaned_data.get('new_size_name') or '').strip()
                        variant.size, _ = Size.objects.get_or_create(
                            name=size_name,
                            defaults={'sort_order': 0},
                        )
                    if not variant.variant_sku:
                        variant.variant_sku = generate_variant_sku(product, variant.color_id, variant.size_id)
                    variant.sale_price = variant.retail_price
                    variant.save()
                if stock_form.has_stock_data() and variant:
                    warehouse = stock_form.cleaned_data.get('warehouse')
                    if not warehouse:
                        warehouse_name = (stock_form.cleaned_data.get('new_warehouse_name') or '').strip()
                        warehouse, _ = Warehouse.objects.get_or_create(
                            name=warehouse_name,
                            defaults={
                                'warehouse_type': Warehouse.TYPE_MAIN,
                                'is_active': True,
                            },
                        )
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
            'can_view_costs': can_view_costs(request.user),
        })


class ProductUpdateView(ManagerRequiredMixin, View):
    template_name = 'products/update.html'

    def get_product(self):
        return get_object_or_404(Product.objects.select_related('category'), pk=self.kwargs['pk'])

    def get_stock_rows(self, product):
        return Stock.objects.select_related('warehouse', 'variant__color', 'variant__size', 'variant__product').filter(
            variant__product=product
        ).order_by('variant__variant_sku', 'warehouse__name')

    def get_variants(self, product):
        return product.variants.select_related('color', 'size').order_by('variant_sku', 'color__name', 'size__sort_order', 'size__name')

    def get(self, request, pk):
        product = self.get_product()
        return render(request, self.template_name, {
            'product': product,
            'form': ProductForm(instance=product),
            'variants': self.get_variants(product),
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
                    self.update_variant_prices(request, product)
                    self.update_stock_rows(request, product)
                messages.success(request, 'تم تحديث المنتج والمخزون')
                return redirect('products:detail', pk=product.pk)
            except (ValidationError, ValueError) as exc:
                message = exc.message if hasattr(exc, 'message') else str(exc)
                form.add_error(None, message)
        return render(request, self.template_name, {
            'product': product,
            'form': form,
            'variants': self.get_variants(product),
            'stock_rows': stock_rows,
            'warehouses': warehouses,
        })

    def update_variant_prices(self, request, product):
        variant_ids = request.POST.getlist('variant_id')
        for variant_id in variant_ids:
            variant = ProductVariant.objects.select_for_update().get(pk=variant_id, product=product)
            raw_retail_price = request.POST.get(f'variant_{variant_id}_retail_price', '').strip()
            raw_wholesale_price = request.POST.get(f'variant_{variant_id}_wholesale_price', '').strip()
            if raw_retail_price == '' or raw_wholesale_price == '':
                raise ValidationError('أدخل سعر القطاعي والجملة لكل لون/مقاس')
            try:
                retail_price = Decimal(raw_retail_price)
                wholesale_price = Decimal(raw_wholesale_price)
            except (InvalidOperation, ValueError):
                raise ValidationError('سعر القطاعي أو الجملة غير صحيح')
            if retail_price < 0 or wholesale_price < 0:
                raise ValidationError('سعر القطاعي أو الجملة لا يمكن أن يكون سالبا')
            changed_fields = []
            if variant.retail_price != retail_price:
                variant.retail_price = retail_price
                changed_fields.append('retail_price')
            if variant.wholesale_price != wholesale_price:
                variant.wholesale_price = wholesale_price
                changed_fields.append('wholesale_price')
            if variant.sale_price != retail_price:
                variant.sale_price = retail_price
                changed_fields.append('sale_price')
            if changed_fields:
                variant.save(update_fields=changed_fields)

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


class ProductDeleteView(ManagerDeleteView):
    model = Product
    success_url = reverse_lazy('products:list')
    success_message = 'تم حذف المنتج'


class BulkPriceUpdateView(ManagerRequiredMixin, View):
    template_name = 'products/bulk_price_update.html'

    def get_queryset(self):
        return ProductVariant.objects.select_related(
            'product',
            'product__category',
            'color',
            'size',
        ).filter(
            is_active=True,
            product__is_active=True,
        ).order_by('product__name', 'product__sku', 'color__name', 'size__sort_order', 'size__name')

    def get_rows(self, posted_prices=None, errors=None):
        rows = []
        posted_prices = posted_prices or {}
        errors = errors or {}
        for variant in self.get_queryset():
            variant_id = str(variant.pk)
            rows.append({
                'variant': variant,
                'price_value': posted_prices.get(variant_id, variant.sale_price),
                'error': errors.get(variant_id),
            })
        return rows

    def get(self, request):
        return render(request, self.template_name, {
            'rows': self.get_rows(),
        })

    def post(self, request):
        variant_ids = request.POST.getlist('variant_id')
        posted_prices = {
            variant_id: request.POST.get(f'price_{variant_id}', '').strip()
            for variant_id in variant_ids
        }
        errors = {}
        parsed_prices = {}

        for variant_id, raw_price in posted_prices.items():
            if raw_price == '':
                errors[variant_id] = 'أدخل السعر'
                continue
            try:
                price = Decimal(raw_price)
            except (InvalidOperation, ValueError):
                errors[variant_id] = 'السعر غير صحيح'
                continue
            if price < 0:
                errors[variant_id] = 'السعر لا يمكن أن يكون سالبا'
                continue
            parsed_prices[variant_id] = price

        if errors:
            return render(request, self.template_name, {
                'rows': self.get_rows(posted_prices=posted_prices, errors=errors),
            })

        updated_count = 0
        with transaction.atomic():
            variants = self.get_queryset().select_for_update().filter(pk__in=parsed_prices.keys())
            for variant in variants:
                new_price = parsed_prices[str(variant.pk)]
                if variant.sale_price != new_price:
                    variant.sale_price = new_price
                    variant.save(update_fields=['sale_price'])
                    updated_count += 1

        messages.success(request, f'تم تحديث أسعار {updated_count} لون/مقاس')
        return redirect('products:bulk_price_update')


class CategoryListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = Category
    template_name = 'products/catalog/categories.html'
    context_object_name = 'categories'
    paginate_by = 20
    export_title = 'قائمة التصنيفات'
    export_filename = 'categories'
    export_columns = (
        ('اسم التصنيف', 'name'),
        ('التصنيف الأب', 'parent'),
        ('الحالة', lambda category: 'نشط' if category.is_active else 'متوقف'),
    )

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


class CategoryDeleteView(ManagerDeleteView):
    model = Category
    success_url = reverse_lazy('products:categories')
    success_message = 'تم حذف التصنيف'


class ColorListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = Color
    template_name = 'products/catalog/colors.html'
    context_object_name = 'colors'
    paginate_by = 20
    ordering = ('name',)
    export_title = 'قائمة الألوان'
    export_filename = 'colors'
    export_columns = (
        ('اسم اللون', 'name'),
        ('كود اللون', 'hex_code'),
    )


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


class ColorDeleteView(ManagerDeleteView):
    model = Color
    success_url = reverse_lazy('products:colors')
    success_message = 'تم حذف اللون'


class SizeListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = Size
    template_name = 'products/catalog/sizes.html'
    context_object_name = 'sizes'
    paginate_by = 20
    export_title = 'قائمة المقاسات'
    export_filename = 'sizes'
    export_columns = (
        ('اسم المقاس', 'name'),
        ('ترتيب العرض', 'sort_order'),
    )


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


class SizeDeleteView(ManagerDeleteView):
    model = Size
    success_url = reverse_lazy('products:sizes')
    success_message = 'تم حذف المقاس'


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
        form.instance.sale_price = form.instance.retail_price
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
        form.instance.sale_price = form.instance.retail_price
        messages.success(self.request, 'تم تحديث اللون والمقاس')
        return super().form_valid(form)


class ProductVariantDeactivateView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        variant = get_object_or_404(ProductVariant, pk=pk)
        variant.is_active = False
        variant.save(update_fields=['is_active'])
        messages.success(request, 'تم إيقاف اللون والمقاس')
        return redirect('products:detail', pk=variant.product_id)


class ProductVariantDeleteView(ManagerDeleteView):
    model = ProductVariant
    success_message = 'تم حذف اللون والمقاس'

    def get_success_url(self):
        return reverse_lazy('products:detail', kwargs={'pk': self.object.product_id})


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
    variants = ProductVariant.objects.filter(product_id=product_id, is_active=True).select_related('product', 'color', 'size')
    data = [
        {
            'id': v.id,
            'variant_sku': v.variant_sku,
            'color': v.color.name if v.color else '',
            'size': v.size.name if v.size else '',
            'pieces_per_dozen': v.product.pieces_per_dozen,
        }
        for v in variants
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب الألوان والمقاسات', 'data': data})


@require_GET
@role_required('manager', 'sales', 'warehouse')
def ajax_get_variant_price(request, variant_id):
    order_type = request.GET.get('order_type', 'b2c')
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id, is_active=True)
    price = variant.wholesale_price if order_type == Order.TYPE_B2B else variant.retail_price
    price = price or variant.sale_price
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


@require_POST
@role_required('manager')
def ajax_quick_create_category(request):
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'success': False, 'message': 'اكتب اسم التصنيف'}, status=400)
    category, _ = Category.objects.get_or_create(name=name, defaults={'is_active': True})
    if not category.is_active:
        category.is_active = True
        category.save(update_fields=['is_active'])
    return JsonResponse({
        'success': True,
        'message': 'تم إضافة التصنيف',
        'data': {'id': category.id, 'name': category.name},
    })


@require_POST
@role_required('manager')
def ajax_quick_create_color(request):
    name = request.POST.get('name', '').strip()
    hex_code = request.POST.get('hex_code', '').strip()
    if not name:
        return JsonResponse({'success': False, 'message': 'اكتب اسم اللون'}, status=400)
    color, created = Color.objects.get_or_create(name=name, defaults={'hex_code': hex_code or None})
    if not created and hex_code and color.hex_code != hex_code:
        color.hex_code = hex_code
        color.save(update_fields=['hex_code'])
    return JsonResponse({
        'success': True,
        'message': 'تم إضافة اللون',
        'data': {'id': color.id, 'name': color.name, 'hex_code': color.hex_code or ''},
    })


@require_POST
@role_required('manager')
def ajax_quick_create_size(request):
    name = request.POST.get('name', '').strip()
    sort_order = request.POST.get('sort_order', '').strip()
    if not name:
        return JsonResponse({'success': False, 'message': 'اكتب اسم المقاس'}, status=400)
    try:
        sort_order_value = int(sort_order or 0)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'ترتيب العرض غير صحيح'}, status=400)
    size, created = Size.objects.get_or_create(name=name, defaults={'sort_order': sort_order_value})
    if not created and sort_order and size.sort_order != sort_order_value:
        size.sort_order = sort_order_value
        size.save(update_fields=['sort_order'])
    return JsonResponse({
        'success': True,
        'message': 'تم إضافة المقاس',
        'data': {'id': size.id, 'name': size.name},
    })


@require_POST
@role_required('manager')
def ajax_quick_create_warehouse(request):
    name = request.POST.get('name', '').strip()
    warehouse_type = request.POST.get('warehouse_type', Warehouse.TYPE_MAIN).strip() or Warehouse.TYPE_MAIN
    if not name:
        return JsonResponse({'success': False, 'message': 'اكتب اسم المخزن'}, status=400)
    if warehouse_type not in {Warehouse.TYPE_MAIN, Warehouse.TYPE_STORE}:
        warehouse_type = Warehouse.TYPE_MAIN
    warehouse, created = Warehouse.objects.get_or_create(
        name=name,
        defaults={'warehouse_type': warehouse_type, 'is_active': True},
    )
    changed_fields = []
    if not warehouse.is_active:
        warehouse.is_active = True
        changed_fields.append('is_active')
    if not created and warehouse.warehouse_type != warehouse_type:
        warehouse.warehouse_type = warehouse_type
        changed_fields.append('warehouse_type')
    if changed_fields:
        warehouse.save(update_fields=changed_fields)
    return JsonResponse({
        'success': True,
        'message': 'تم إضافة المخزن',
        'data': {'id': warehouse.id, 'name': warehouse.name},
    })


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

    stock_filter = Q()
    if warehouse_obj:
        stock_filter = Q(warehouse=warehouse_obj)
    stock_map = {}
    for row in Stock.objects.filter(variant__product__in=qs[:100], **({'warehouse': warehouse_obj} if warehouse_obj else {})).values('variant_id').annotate(total=Sum('quantity')):
        stock_map[row['variant_id']] = row['total']

    data = []
    for product in qs[:100]:
        variants = []
        for variant in product.variants.all():
            quantity = stock_map.get(variant.id, 0)
            variants.append({
                'id': variant.id,
                'code': variant.variant_sku,
                'barcode': variant.barcode or '',
                'color': variant.color.name if variant.color else '',
                'size': variant.size.name if variant.size else '',
                'image': variant.image.url if variant.image else '',
                'sale_price': str(variant.sale_price),
                'pieces_per_dozen': variant.product.pieces_per_dozen,
                'quantity': quantity,
                'is_active': variant.is_active,
            })
        data.append({
            'id': product.id,
            'name': product.name,
            'code': product.sku,
            'category': product.category.name if product.category else '',
            'pieces_per_dozen': product.pieces_per_dozen,
            'image': product.image.url if product.image else '',
            'variants': variants,
        })
    return JsonResponse({'success': True, 'message': 'تم جلب المنتجات', 'data': data})

# Create your views here.
