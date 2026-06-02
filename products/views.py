from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin

from .forms import ProductForm
from .models import Category, Product, ProductVariant


class ProductListView(RoleRequiredMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = Product
    template_name = 'products/list.html'
    context_object_name = 'products'
    paginate_by = 20

    def get_queryset(self):
        qs = Product.objects.select_related('category').prefetch_related('variants').annotate(variant_count=Count('variants'))
        q = self.request.GET.get('q')
        category = self.request.GET.get('category')
        status = self.request.GET.get('status')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
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


class ProductCreateView(ManagerRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'products/create.html'
    success_url = reverse_lazy('products:list')

    def form_valid(self, form):
        messages.success(self.request, 'تم إضافة المنتج')
        return super().form_valid(form)


class ProductUpdateView(ManagerRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'products/update.html'
    success_url = reverse_lazy('products:list')

    def form_valid(self, form):
        messages.success(self.request, 'تم تعديل المنتج')
        return super().form_valid(form)


class ProductDeactivateView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = False
        product.save(update_fields=['is_active'])
        messages.success(request, 'تم إيقاف المنتج')
        return redirect('products:list')


@require_GET
def ajax_search_products(request):
    q = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True)
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(variants__variant_sku__icontains=q)).distinct()
    data = [
        {'id': p.id, 'name': p.name, 'sku': p.sku, 'retail_price': str(p.retail_price), 'wholesale_price': str(p.wholesale_price)}
        for p in products[:12]
    ]
    return JsonResponse({'success': True, 'message': 'تم جلب المنتجات', 'data': data})


@require_GET
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
    return JsonResponse({'success': True, 'message': 'تم جلب المتغيرات', 'data': data})


@require_GET
def ajax_get_variant_price(request, variant_id):
    order_type = request.GET.get('order_type', 'b2c')
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id, is_active=True)
    price = variant.product.wholesale_price if order_type == 'b2b' else variant.product.retail_price
    return JsonResponse({'success': True, 'message': 'تم جلب السعر', 'data': {'price': str(price)}})

# Create your views here.
