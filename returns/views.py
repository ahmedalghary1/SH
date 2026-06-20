from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, SalesRequiredMixin
from config.delete_views import ManagerDeleteView
from config.exports import ExportListMixin
from products.models import ProductVariant

from .forms import CompleteReturnForm, ExchangeItemForm, ReturnItemForm, SalesReturnCreateForm
from .models import SalesReturn, SalesReturnItem
from .services import (
    _line_refund_unit_price,
    add_exchange_item,
    add_return_item,
    approve_sales_return,
    calculate_available_return_quantity,
    complete_sales_return,
    create_sales_return,
)


def _validation_error_message(exc):
    return getattr(exc, 'message', None) or '; '.join(getattr(exc, 'messages', [str(exc)]))


class SalesReturnListView(RoleRequiredMixin, ExportListMixin, ListView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = SalesReturn
    template_name = 'returns/list.html'
    context_object_name = 'returns'
    paginate_by = 20
    export_title = 'قائمة المرتجعات'
    export_filename = 'returns'
    export_columns = (
        ('رقم المرتجع', 'id'),
        ('رقم الطلب', 'order.order_number'),
        ('العميل', 'customer'),
        ('النوع', 'get_return_type_display'),
        ('الحالة', 'get_status_display'),
        ('قيمة الاسترداد', 'refund_amount'),
        ('الموظف', 'created_by'),
        ('التاريخ', 'created_at'),
        ('السبب', 'reason'),
    )

    def get_queryset(self):
        qs = SalesReturn.objects.select_related('order', 'customer', 'created_by').order_by('-created_at')
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(pk__icontains=q) |
                Q(order__order_number__icontains=q) |
                Q(customer__name__icontains=q)
            )
        return qs


class SimpleReturnCreateView(SalesRequiredMixin, FormView):
    template_name = 'returns/simple_create.html'
    form_class = SalesReturnCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if self.request.method == 'GET':
            data = self.request.GET.copy()
            invoice_number = data.get('invoice_number')
            if invoice_number:
                data.setdefault('return_type', SalesReturn.TYPE_PARTIAL_RETURN)
                kwargs['data'] = data
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial['return_type'] = SalesReturn.TYPE_PARTIAL_RETURN
        if self.request.GET.get('invoice_number'):
            initial['invoice_number'] = self.request.GET.get('invoice_number')
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get('form')
        if form and form.is_bound:
            form.is_valid()
        order = getattr(self, 'order_preview', None) or getattr(form, 'order', None)
        context['order_preview'] = order
        context['item_rows'] = self._build_item_rows(order) if order else []
        context['condition_choices'] = SalesReturnItem.CONDITION_CHOICES
        context['SalesReturn'] = SalesReturn
        context['SalesReturnItem'] = SalesReturnItem
        context['searched_invoice_number'] = (
            self.request.POST.get('invoice_number') or self.request.GET.get('invoice_number') or ''
        )
        return context

    def _build_item_rows(self, order):
        rows = []
        for item in order.items.all():
            available_quantity = calculate_available_return_quantity(item) if item.variant_id else 0
            posted_quantity = self.request.POST.get(f'quantity_{item.pk}')
            is_post = self.request.method == 'POST'
            unit_price = _line_refund_unit_price(item)
            try:
                preview_quantity = Decimal(str(posted_quantity if posted_quantity is not None else available_quantity))
            except (InvalidOperation, ValueError):
                preview_quantity = Decimal('0')
            rows.append({
                'item': item,
                'available_quantity': available_quantity,
                'quantity_value': posted_quantity if posted_quantity is not None else available_quantity,
                'selected': self.request.POST.get(f'selected_{item.pk}') == 'on' if is_post else False,
                'condition_value': self.request.POST.get(f'condition_{item.pk}', SalesReturnItem.CONDITION_GOOD),
                'return_to_stock': self.request.POST.get(f'return_to_stock_{item.pk}', 'on') == 'on',
                'notes_value': self.request.POST.get(f'notes_{item.pk}', ''),
                'unit_price': unit_price,
                'refund_amount': unit_price * preview_quantity,
            })
        return rows

    def _selected_return_items(self, order):
        selected_items = []
        errors = []
        condition_values = {choice[0] for choice in SalesReturnItem.CONDITION_CHOICES}
        for row in self._build_item_rows(order):
            item = row['item']
            if self.request.POST.get(f'selected_{item.pk}') != 'on':
                continue
            raw_quantity = str(self.request.POST.get(f'quantity_{item.pk}', '0')).strip() or '0'
            try:
                quantity = int(raw_quantity)
            except ValueError:
                errors.append(f'كمية {item.variant} غير صحيحة')
                continue
            if quantity < 0:
                errors.append(f'كمية {item.variant} لا يمكن أن تكون سالبة')
                continue
            if quantity == 0:
                errors.append(f'حدد كمية أكبر من صفر للصنف {item.variant}')
                continue
            if not item.variant_id:
                errors.append('لا يمكن إرجاع صنف بدون متغير منتج')
                continue
            if quantity > row['available_quantity']:
                errors.append(f'كمية {item.variant} أكبر من المتاح للإرجاع')
                continue
            condition = self.request.POST.get(f'condition_{item.pk}', SalesReturnItem.CONDITION_GOOD)
            if condition not in condition_values:
                errors.append(f'حالة {item.variant} غير صحيحة')
                continue
            selected_items.append({
                'original_order_item': item,
                'quantity': quantity,
                'condition': condition,
                'return_to_stock': self.request.POST.get(f'return_to_stock_{item.pk}') == 'on',
                'notes': self.request.POST.get(f'notes_{item.pk}', '').strip(),
            })
        if not selected_items and not errors:
            errors.append('حدد كمية مرتجع لصنف واحد على الأقل')
        return selected_items, errors

    def form_valid(self, form):
        order = form.order
        self.order_preview = order
        selected_items, errors = self._selected_return_items(order)
        if errors:
            for error in errors:
                form.add_error(None, error)
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                sales_return = create_sales_return(
                    order=order,
                    return_type=form.cleaned_data['return_type'],
                    reason=form.cleaned_data.get('reason') or '',
                    user=self.request.user,
                )
                for item_data in selected_items:
                    add_return_item(sales_return=sales_return, **item_data)
            messages.success(self.request, 'تم تسجيل مسودة المرتجع بالأصناف المحددة')
            return redirect('returns:detail', pk=sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class SimpleExchangeCreateView(SalesRequiredMixin, FormView):
    template_name = 'returns/simple_exchange.html'
    form_class = SalesReturnCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if self.request.method == 'GET' and self.request.GET.get('invoice_number'):
            data = self.request.GET.copy()
            data.setdefault('return_type', SalesReturn.TYPE_EXCHANGE)
            kwargs['data'] = data
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial['return_type'] = SalesReturn.TYPE_EXCHANGE
        if self.request.GET.get('invoice_number'):
            initial['invoice_number'] = self.request.GET.get('invoice_number')
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get('form')
        if form and form.is_bound:
            form.is_valid()
        order = getattr(self, 'order_preview', None) or getattr(form, 'order', None)
        context['order_preview'] = order
        context['item_rows'] = self._build_item_rows(order) if order else []
        context['available_variants'] = ProductVariant.objects.filter(is_active=True).select_related('product', 'color', 'size') if order else []
        context['SalesReturn'] = SalesReturn
        context['searched_invoice_number'] = (
            self.request.POST.get('invoice_number') or self.request.GET.get('invoice_number') or ''
        )
        return context

    def _build_item_rows(self, order):
        rows = []
        for item in order.items.all():
            available_quantity = calculate_available_return_quantity(item) if item.variant_id else 0
            posted_quantity = self.request.POST.get(f'quantity_{item.pk}')
            is_post = self.request.method == 'POST'
            unit_price = _line_refund_unit_price(item)
            rows.append({
                'item': item,
                'available_quantity': available_quantity,
                'quantity_value': posted_quantity if posted_quantity is not None else available_quantity,
                'selected': self.request.POST.get(f'selected_{item.pk}') == 'on' if is_post else False,
                'unit_price': unit_price,
            })
        return rows

    def form_valid(self, form):
        order = form.order
        self.order_preview = order
        selected_items, errors = self._selected_return_items(order)
        new_items, new_errors = self._get_new_items()
        
        if errors or new_errors:
            for error in errors + new_errors:
                form.add_error(None, error)
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                sales_return = create_sales_return(
                    order=order,
                    return_type=SalesReturn.TYPE_EXCHANGE,
                    reason=form.cleaned_data.get('reason') or '',
                    user=self.request.user,
                )
                for item_data in selected_items:
                    add_return_item(sales_return=sales_return, **item_data)
                for new_item in new_items:
                    add_exchange_item(sales_return=sales_return, **new_item)
            messages.success(self.request, 'تم تسجيل مسودة الاستبدال')
            return redirect('returns:detail', pk=sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)

    def _selected_return_items(self, order):
        selected_items = []
        errors = []
        for row in self._build_item_rows(order):
            item = row['item']
            if self.request.POST.get(f'selected_{item.pk}') != 'on':
                continue
            raw_quantity = str(self.request.POST.get(f'quantity_{item.pk}', '0')).strip() or '0'
            try:
                quantity = int(raw_quantity)
            except ValueError:
                errors.append(f'كمية {item.variant} غير صحيحة')
                continue
            if quantity <= 0:
                errors.append(f'كمية {item.variant} يجب أن تكون أكبر من صفر')
                continue
            if quantity > row['available_quantity']:
                errors.append(f'كمية {item.variant} أكبر من المتاح للإرجاع')
                continue
            selected_items.append({
                'original_order_item': item,
                'quantity': quantity,
                'condition': SalesReturnItem.CONDITION_GOOD,
                'return_to_stock': True,
                'notes': '',
            })
        if not selected_items and not errors:
            errors.append('حدد كمية مرتجع لصنف واحد على الأقل')
        return selected_items, errors

    def _get_new_items(self):
        new_items = []
        errors = []
        for key in self.request.POST:
            if key.startswith('new_product_variant_'):
                index = key.replace('new_product_variant_', '')
                variant_id = self.request.POST.get(key)
                quantity = self.request.POST.get(f'new_quantity_{index}', '0')
                price = self.request.POST.get(f'new_price_{index}', '0')
                
                if not variant_id:
                    continue
                
                try:
                    variant = ProductVariant.objects.get(pk=variant_id, is_active=True)
                except ProductVariant.DoesNotExist:
                    errors.append('المنتج المحدد غير موجود')
                    continue
                
                try:
                    qty = int(quantity)
                except ValueError:
                    errors.append(f'كمية المنتج {variant} غير صحيحة')
                    continue
                
                if qty <= 0:
                    errors.append(f'كمية المنتج {variant} يجب أن تكون أكبر من صفر')
                    continue
                
                try:
                    price_val = Decimal(str(price))
                except (InvalidOperation, ValueError):
                    errors.append(f'سعر المنتج {variant} غير صحيح')
                    continue
                
                # Find the corresponding old item
                old_item = None
                for row in self._build_item_rows(self.order_preview):
                    row_item = row['item']
                    if self.request.POST.get(f'selected_{row_item.pk}') == 'on':
                        old_item = row_item
                        break
                
                if not old_item:
                    errors.append('يجب تحديد صنف قديم للاستبدال')
                    continue
                
                new_items.append({
                    'old_order_item': old_item,
                    'new_product_variant': variant,
                    'quantity': qty,
                    'new_unit_price': price_val,
                    'notes': '',
                })
        
        if not new_items and not errors:
            errors.append('حدد منتج جديد واحد على الأقل')
        
        return new_items, errors


class SalesReturnCreateView(SalesRequiredMixin, FormView):
    template_name = 'returns/create.html'
    form_class = SalesReturnCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if self.request.method == 'GET' and self.request.GET.get('invoice_number'):
            data = self.request.GET.copy()
            data.setdefault('return_type', SalesReturn.TYPE_PARTIAL_RETURN)
            kwargs['data'] = data
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial['return_type'] = SalesReturn.TYPE_PARTIAL_RETURN
        if self.request.GET.get('invoice_number'):
            initial['invoice_number'] = self.request.GET.get('invoice_number')
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get('form')
        if form and form.is_bound:
            form.is_valid()
        order = getattr(self, 'order_preview', None) or getattr(form, 'order', None)
        context['order_preview'] = order
        context['item_rows'] = self._build_item_rows(order) if order else []
        context['condition_choices'] = SalesReturnItem.CONDITION_CHOICES
        context['searched_invoice_number'] = (
            self.request.POST.get('invoice_number') or self.request.GET.get('invoice_number') or ''
        )
        return context

    def _build_item_rows(self, order):
        rows = []
        for item in order.items.all():
            available_quantity = calculate_available_return_quantity(item) if item.variant_id else 0
            posted_quantity = self.request.POST.get(f'quantity_{item.pk}')
            is_post = self.request.method == 'POST'
            rows.append({
                'item': item,
                'available_quantity': available_quantity,
                'quantity_value': posted_quantity if posted_quantity is not None else available_quantity,
                'selected': self.request.POST.get(f'selected_{item.pk}') == 'on' if is_post else False,
                'condition_value': self.request.POST.get(f'condition_{item.pk}', SalesReturnItem.CONDITION_GOOD),
                'return_to_stock': self.request.POST.get(f'return_to_stock_{item.pk}', 'on') == 'on',
                'notes_value': self.request.POST.get(f'notes_{item.pk}', ''),
            })
        return rows

    def _selected_return_items(self, order):
        selected_items = []
        errors = []
        condition_values = {choice[0] for choice in SalesReturnItem.CONDITION_CHOICES}
        for row in self._build_item_rows(order):
            item = row['item']
            if self.request.POST.get(f'selected_{item.pk}') != 'on':
                continue
            raw_quantity = str(self.request.POST.get(f'quantity_{item.pk}', '0')).strip() or '0'
            try:
                quantity = int(raw_quantity)
            except ValueError:
                errors.append(f'كمية {item.variant} غير صحيحة')
                continue
            if quantity < 0:
                errors.append(f'كمية {item.variant} لا يمكن أن تكون سالبة')
                continue
            if quantity == 0:
                errors.append(f'حدد كمية أكبر من صفر للصنف {item.variant}')
                continue
            if not item.variant_id:
                errors.append('لا يمكن إرجاع صنف بدون متغير منتج')
                continue
            if quantity > row['available_quantity']:
                errors.append(f'كمية {item.variant} أكبر من المتاح للإرجاع')
                continue
            condition = self.request.POST.get(f'condition_{item.pk}', SalesReturnItem.CONDITION_GOOD)
            if condition not in condition_values:
                errors.append(f'حالة {item.variant} غير صحيحة')
                continue
            selected_items.append({
                'original_order_item': item,
                'quantity': quantity,
                'condition': condition,
                'return_to_stock': self.request.POST.get(f'return_to_stock_{item.pk}') == 'on',
                'notes': self.request.POST.get(f'notes_{item.pk}', '').strip(),
            })
        if not selected_items and not errors:
            errors.append('حدد كمية مرتجع لصنف واحد على الأقل')
        return selected_items, errors

    def form_valid(self, form):
        order = form.order
        self.order_preview = order
        selected_items, errors = self._selected_return_items(order)
        if errors:
            for error in errors:
                form.add_error(None, error)
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                sales_return = create_sales_return(
                    order=order,
                    return_type=form.cleaned_data['return_type'],
                    reason=form.cleaned_data.get('reason') or '',
                    user=self.request.user,
                )
                for item_data in selected_items:
                    add_return_item(sales_return=sales_return, **item_data)
            messages.success(self.request, 'تم تسجيل مسودة المرتجع بالأصناف المحددة')
            return redirect('returns:detail', pk=sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class SalesReturnDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    model = SalesReturn
    template_name = 'returns/detail.html'
    context_object_name = 'sales_return'

    def get_queryset(self):
        qs = SalesReturn.objects.select_related('order', 'customer', 'created_by', 'approved_by', 'completed_by').prefetch_related(
            'items__product_variant__product',
            'exchange_items__new_product_variant__product',
        )
        if self.request.user.role == 'sales' and not self.request.user.is_superuser:
            qs = qs.filter(created_by=self.request.user)
        return qs


class ReturnItemAddView(SalesRequiredMixin, FormView):
    template_name = 'returns/item_form.html'
    form_class = ReturnItemForm

    def dispatch(self, request, *args, **kwargs):
        self.sales_return = get_object_or_404(SalesReturn, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['sales_return'] = self.sales_return
        return kwargs

    def form_valid(self, form):
        try:
            add_return_item(sales_return=self.sales_return, **form.cleaned_data)
            messages.success(self.request, 'تمت إضافة الصنف المرتجع')
            return redirect('returns:detail', pk=self.sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class ExchangeItemAddView(SalesRequiredMixin, FormView):
    template_name = 'returns/exchange_form.html'
    form_class = ExchangeItemForm

    def dispatch(self, request, *args, **kwargs):
        self.sales_return = get_object_or_404(SalesReturn, pk=kwargs['pk'], return_type=SalesReturn.TYPE_EXCHANGE)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['sales_return'] = self.sales_return
        return kwargs

    def form_valid(self, form):
        try:
            add_exchange_item(sales_return=self.sales_return, **form.cleaned_data)
            messages.success(self.request, 'تمت إضافة صنف الاستبدال')
            return redirect('returns:detail', pk=self.sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class SalesReturnApproveView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        sales_return = get_object_or_404(SalesReturn, pk=pk)
        try:
            approve_sales_return(sales_return=sales_return, user=request.user)
            messages.success(request, 'تم اعتماد المرتجع')
        except ValidationError as exc:
            messages.error(request, _validation_error_message(exc))
        return redirect('returns:detail', pk=pk)


class SalesReturnCompleteView(ManagerRequiredMixin, FormView):
    template_name = 'returns/complete.html'
    form_class = CompleteReturnForm

    def dispatch(self, request, *args, **kwargs):
        self.sales_return = get_object_or_404(SalesReturn, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            complete_sales_return(
                sales_return=self.sales_return,
                user=self.request.user,
            )
            messages.success(self.request, 'تم إكمال المرتجع وتسجيل آثاره')
            return redirect('returns:detail', pk=self.sales_return.pk)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class SalesReturnRejectView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        sales_return = get_object_or_404(SalesReturn, pk=pk)
        if sales_return.status == SalesReturn.STATUS_DRAFT:
            sales_return.status = SalesReturn.STATUS_REJECTED
            sales_return.save(update_fields=['status'])
            messages.success(request, 'تم رفض المرتجع')
        else:
            messages.error(request, 'يمكن رفض المرتجع من حالة المسودة فقط')
        return redirect('returns:detail', pk=pk)


class SalesReturnDeleteView(ManagerDeleteView):
    model = SalesReturn
    success_url = reverse_lazy('returns:list')
    success_message = 'تم حذف المرتجع'


class ReturnReasonReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'returns/reports/reasons.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reasons'] = SalesReturn.objects.values('reason').annotate(count=Count('id'), total=Sum('refund_amount')).order_by('-count')
        return context


class ProductReturnReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'returns/reports/products.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = SalesReturnItem.objects.filter(
            sales_return__status=SalesReturn.STATUS_COMPLETED,
        ).values('product_variant__product__name').annotate(qty=Sum('quantity'), total=Sum('refund_amount')).order_by('-qty')
        return context


class DailyReturnsReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'returns/reports/daily.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                target_date = parse_date(date_str)
            except:
                target_date = today
        else:
            target_date = today
        
        returns = SalesReturn.objects.filter(
            created_at__date=target_date,
            status=SalesReturn.STATUS_COMPLETED,
        ).select_related('order', 'customer', 'created_by')
        
        total_refund = returns.aggregate(v=Sum('refund_amount'))['v'] or 0
        total_count = returns.count()
        
        # Returns by user
        returns_by_user = returns.values('created_by__username').annotate(
            count=Count('id'),
            total=Sum('refund_amount')
        ).order_by('-count')
        
        # Damaged returns
        damaged_returns = SalesReturnItem.objects.filter(
            sales_return__created_at__date=target_date,
            sales_return__status=SalesReturn.STATUS_COMPLETED,
            condition=SalesReturnItem.CONDITION_DAMAGED,
        ).values('product_variant__product__name').annotate(qty=Sum('quantity')).order_by('-qty')
        
        context.update({
            'target_date': target_date,
            'returns': returns,
            'total_refund': total_refund,
            'total_count': total_count,
            'returns_by_user': returns_by_user,
            'damaged_returns': damaged_returns,
        })
        return context
