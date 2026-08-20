from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from datetime import datetime

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from accounts.permissions import ManagerRequiredMixin, RoleRequiredMixin, can_view_costs, SalesRequiredMixin
from config.delete_views import ManagerDeleteView
from config.date_ranges import PERIOD_CHOICES, filter_by_date_period
from config.exports import ExportListMixin
from customers.models import Customer
from customers.services import visible_customers_for_user
from orders.models import Order

from .forms import CashAccountForm, CashAccountStatementForm, CustomerCollectionForm, CustomerPaymentEditForm, ExpenseForm, SalesRepStatementForm, TransferForm, SupplierPaymentForm
from .models import CashAccount, PaymentTransaction
from .services import add_expense, build_cash_account_statement, build_customer_statement, collect_customer_balance_payment, collect_order_payment, delete_transaction, record_customer_allowed_discount, record_customer_payment, record_customer_refund_payment, record_supplier_payment, replace_customer_payment, replace_expense, transfer_between_accounts


def _validation_error_message(exc):
    return getattr(exc, 'message', None) or '; '.join(getattr(exc, 'messages', [str(exc)]))


class CashDashboardView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/cash.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        default_account = CashAccount.get_default()
        cash_drawer = CashAccount.get_cash_drawer()
        all_cash_accounts = CashAccount.objects.filter(is_active=True).select_related('assigned_user').order_by(
            'account_type',
            'name',
        )

        selected_account_id = self.request.GET.get('account', '').strip()
        selected_account = all_cash_accounts.filter(pk=selected_account_id).first() if selected_account_id.isdigit() else None
        scoped_accounts = all_cash_accounts.filter(pk=selected_account.pk) if selected_account else all_cash_accounts
        account_ids = list(scoped_accounts.values_list('pk', flat=True))

        date_from = parse_date(self.request.GET.get('date_from') or '') or today
        date_to = parse_date(self.request.GET.get('date_to') or '') or date_from
        if date_to < date_from:
            date_from, date_to = date_to, date_from

        transactions_base = PaymentTransaction.objects.filter(cash_account_id__in=account_ids)
        period_transactions = transactions_base.filter(
            transaction_date__gte=date_from,
            transaction_date__lte=date_to,
        ).select_related(
            'cash_account',
            'related_order',
            'related_customer',
            'related_supplier',
            'related_sales_rep',
            'created_by',
        )

        sale_type = self.request.GET.get('sale_type', '').strip()
        sort = self.request.GET.get('sort', 'datetime_desc').strip()
        sort_options = {
            'amount_asc': ('amount', 'transaction_date', 'transaction_time', 'pk'),
            'amount_desc': ('-amount', '-transaction_date', '-transaction_time', '-pk'),
            'datetime_asc': ('transaction_date', 'transaction_time', 'pk'),
            'datetime_desc': ('-transaction_date', '-transaction_time', '-pk'),
        }
        if sort not in sort_options:
            sort = 'datetime_desc'

        transactions = period_transactions
        if sale_type in {Order.TYPE_B2C, Order.TYPE_B2B}:
            transactions = transactions.filter(related_order__order_type=sale_type)
        transactions = transactions.order_by(*sort_options[sort])

        total_in = transactions.filter(direction=PaymentTransaction.DIRECTION_IN).aggregate(v=Sum('amount'))['v'] or 0
        total_out = transactions.filter(direction=PaymentTransaction.DIRECTION_OUT).aggregate(v=Sum('amount'))['v'] or 0
        period_net = total_in - total_out
        filtered_amount_total = transactions.aggregate(v=Sum('amount'))['v'] or 0
        current_balance = scoped_accounts.aggregate(v=Sum('balance'))['v'] or 0
        base_total_in = period_transactions.filter(direction=PaymentTransaction.DIRECTION_IN).aggregate(v=Sum('amount'))['v'] or 0
        base_total_out = period_transactions.filter(direction=PaymentTransaction.DIRECTION_OUT).aggregate(v=Sum('amount'))['v'] or 0
        opening_balance = current_balance - (base_total_in - base_total_out)

        cash_sales = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            related_order__isnull=False
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        customer_collections = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            related_order__isnull=True
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        supplier_payments = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        expenses = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_EXPENSE
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        cash_refunds = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_REFUND
        ).aggregate(v=Sum('amount'))['v'] or 0

        context.update({
            'opening_balance': opening_balance,
            'cash_sales': cash_sales,
            'customer_collections': customer_collections,
            'supplier_payments': supplier_payments,
            'expenses': expenses,
            'cash_refunds': cash_refunds,
            'total_in': total_in,
            'total_out': total_out,
            'period_net': period_net,
            'period_net_is_negative': period_net < 0,
            'filtered_amount_total': filtered_amount_total,
            'current_balance': current_balance,
            'main_account': default_account,
            'cash_drawer': cash_drawer,
            'all_cash_accounts': all_cash_accounts,
            'selected_account': selected_account,
            'filters': {
                'account': selected_account_id if selected_account else '',
                'date_from': date_from.isoformat(),
                'date_to': date_to.isoformat(),
                'sale_type': sale_type if sale_type in {Order.TYPE_B2C, Order.TYPE_B2B} else '',
                'sort': sort,
            },
            'sale_type_choices': Order.ORDER_TYPE_CHOICES,
            'period_label': date_from.strftime('%Y-%m-%d') if date_from == date_to else f'{date_from:%Y-%m-%d} - {date_to:%Y-%m-%d}',
            'transactions': transactions[:50],
        })
        return context


class CashShiftView(SalesRequiredMixin, TemplateView):
    template_name = 'finance/cash_shift.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        default_account = CashAccount.get_default()
        
        # الحصول على معاملات اليوم للمستخدم الحالي فقط
        transactions = PaymentTransaction.objects.filter(
            cash_account=default_account,
            transaction_date=today,
            created_by=self.request.user
        ).select_related('created_by').order_by('-created_at')
        
        # حساب الإحصائيات للمستخدم الحالي
        cash_sales = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            related_order__isnull=False
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        cash_refunds = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_REFUND
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        total_in = transactions.filter(direction=PaymentTransaction.DIRECTION_IN).aggregate(v=Sum('amount'))['v'] or 0
        total_out = transactions.filter(direction=PaymentTransaction.DIRECTION_OUT).aggregate(v=Sum('amount'))['v'] or 0
        
        context.update({
            'cash_sales': cash_sales,
            'cash_refunds': cash_refunds,
            'total_in': total_in,
            'total_out': total_out,
            'transactions': transactions[:50],
        })
        return context


class CashAccountListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = CashAccount
    template_name = 'finance/accounts/list.html'
    context_object_name = 'accounts'
    paginate_by = 20
    export_title = 'قائمة الحسابات المالية'
    export_filename = 'cash-accounts'
    export_columns = (
        ('اسم الحساب', 'name'),
        ('النوع', 'get_account_type_display'),
        ('المسؤول', 'assigned_user'),
        ('الرصيد', 'balance'),
        ('السماح بالسحب على المكشوف', lambda account: 'نعم' if account.allow_overdraft else 'لا'),
        ('الحالة', lambda account: 'نشط' if account.is_active else 'متوقف'),
    )

    def get_queryset(self):
        return CashAccount.objects.select_related('assigned_user').order_by('account_type', 'name')


class CashAccountCreateView(ManagerRequiredMixin, CreateView):
    model = CashAccount
    form_class = CashAccountForm
    template_name = 'finance/accounts/form.html'
    success_url = reverse_lazy('finance:accounts')

    def form_valid(self, form):
        messages.success(self.request, 'تم إنشاء الحساب المالي')
        return super().form_valid(form)


class CashAccountUpdateView(ManagerRequiredMixin, UpdateView):
    model = CashAccount
    form_class = CashAccountForm
    template_name = 'finance/accounts/form.html'
    success_url = reverse_lazy('finance:accounts')

    def form_valid(self, form):
        messages.success(self.request, 'تم تحديث الحساب المالي')
        return super().form_valid(form)


class CashAccountDeleteView(ManagerDeleteView):
    model = CashAccount
    success_url = reverse_lazy('finance:accounts')
    success_message = 'تم حذف الحساب المالي'
    protected_message = 'لا يمكن حذف هذه الخزنة لأنها مرتبطة بحركات مالية. يمكنك إيقافها بدل حذفها للحفاظ على سلامة البيانات.'

    def form_valid(self, form):
        account = self.get_object()
        if account.balance != 0:
            messages.error(self.request, 'لا يمكن حذف خزنة رصيدها غير صفر. صفّر الرصيد أولاً ثم أعد المحاولة.')
            return redirect(self.get_success_url())
        if account.account_type == CashAccount.TYPE_CASH and account.is_active:
            has_other_active_cash = CashAccount.objects.filter(
                account_type=CashAccount.TYPE_CASH,
                is_active=True,
            ).exclude(pk=account.pk).exists()
            if not has_other_active_cash:
                messages.error(self.request, 'لا يمكن حذف آخر خزنة نقدية نشطة في النظام.')
                return redirect(self.get_success_url())
        return super().form_valid(form)


class CashAccountDetailView(ManagerRequiredMixin, DetailView):
    model = CashAccount
    template_name = 'finance/accounts/detail.html'
    context_object_name = 'account'
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transactions = self.object.transactions.select_related(
            'related_order',
            'related_customer',
            'related_sales_rep',
            'related_supplier',
            'created_by',
        )
        transaction_type = self.request.GET.get('type', '').strip()
        direction = self.request.GET.get('direction', '').strip()
        date_from = parse_date(self.request.GET.get('date_from', ''))
        date_to = parse_date(self.request.GET.get('date_to', ''))
        if transaction_type:
            transactions = transactions.filter(transaction_type=transaction_type)
        if direction:
            transactions = transactions.filter(direction=direction)
        if date_from:
            transactions = transactions.filter(transaction_date__gte=date_from)
        if date_to:
            transactions = transactions.filter(transaction_date__lte=date_to)

        total_in = transactions.filter(direction=PaymentTransaction.DIRECTION_IN).aggregate(v=Sum('amount'))['v'] or 0
        total_out = transactions.filter(direction=PaymentTransaction.DIRECTION_OUT).aggregate(v=Sum('amount'))['v'] or 0
        paginator = Paginator(transactions, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get('page'))
        context['transactions'] = page_obj.object_list
        context['page_obj'] = page_obj
        context['paginator'] = paginator
        context['is_paginated'] = page_obj.has_other_pages()
        context['total_in'] = total_in
        context['total_out'] = total_out
        context['net_total'] = total_in - total_out
        context['transaction_type_choices'] = PaymentTransaction.TRANSACTION_TYPE_CHOICES
        context['direction_choices'] = PaymentTransaction.DIRECTION_CHOICES
        context['filters'] = {
            'type': transaction_type,
            'direction': direction,
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        query = self.request.GET.copy()
        query.pop('page', None)
        context['pagination_query'] = query.urlencode()
        return context


class TransactionListView(ManagerRequiredMixin, ExportListMixin, ListView):
    model = PaymentTransaction
    template_name = 'finance/transactions/list.html'
    context_object_name = 'transactions'
    paginate_by = 30
    export_title = 'قائمة المعاملات المالية'
    export_filename = 'transactions'
    export_columns = (
        ('تاريخ الحركة', 'transaction_date'),
        ('وقت التسجيل', 'created_at'),
        ('النوع', 'get_transaction_type_display'),
        ('الاتجاه', 'get_direction_display'),
        ('المبلغ', 'amount'),
        ('الحساب', 'cash_account'),
        ('الطلب', 'related_order'),
        ('العميل', 'related_customer'),
        ('المورد', 'related_supplier'),
        ('الموظف', 'created_by'),
        ('ملاحظات', 'notes'),
    )

    def get_queryset(self):
        qs = PaymentTransaction.objects.select_related(
            'cash_account', 'related_order', 'related_customer', 'related_sales_rep', 'related_supplier', 'created_by'
        )
        transaction_type = self.request.GET.get('type')
        direction = self.request.GET.get('direction')
        if transaction_type:
            qs = qs.filter(transaction_type=transaction_type)
        if direction:
            qs = qs.filter(direction=direction)
        qs, self.date_filter = filter_by_date_period(qs, self.request.GET, 'transaction_date')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['transaction_type_choices'] = PaymentTransaction.TRANSACTION_TYPE_CHOICES
        context['direction_choices'] = PaymentTransaction.DIRECTION_CHOICES
        context['filters'] = {
            'type': self.request.GET.get('type', ''),
            'direction': self.request.GET.get('direction', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        selected_type = self.request.GET.get('type', '')
        context['invoice_section'] = (
            'receipts' if selected_type == PaymentTransaction.TYPE_CUSTOMER_PAYMENT
            else 'expenses' if selected_type == PaymentTransaction.TYPE_EXPENSE
            else ''
        )
        context['page_title'] = (
            'سندات القبض' if context['invoice_section'] == 'receipts'
            else 'سندات الصرف' if context['invoice_section'] == 'expenses'
            else 'الحركات المالية'
        )
        context['period_choices'] = PERIOD_CHOICES
        context['date_filter'] = getattr(self, 'date_filter', {})
        return context


class PaymentTransactionDeleteView(ManagerDeleteView):
    model = PaymentTransaction
    success_url = reverse_lazy('finance:transactions')
    success_message = 'تم حذف الحركة المالية'

    def get_queryset(self):
        return super().get_queryset().filter(transaction_type__in=[
            PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            PaymentTransaction.TYPE_EXPENSE,
        ])

    def form_valid(self, form):
        success_url = self.get_success_url()
        try:
            delete_transaction(payment_transaction=self.get_object(), user=self.request.user)
            messages.success(self.request, self.success_message)
            return redirect(success_url)
        except ValidationError as exc:
            form.add_error(None, getattr(exc, 'message', str(exc)))
            return self.form_invalid(form)


class ExpenseCreateView(ManagerRequiredMixin, FormView):
    template_name = 'finance/transactions/expense.html'
    form_class = ExpenseForm
    success_url = reverse_lazy('finance:transactions')

    def form_valid(self, form):
        try:
            add_expense(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم تسجيل المصروف وخصمه من الخزنة')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class CustomerCollectionView(RoleRequiredMixin, FormView):
    allowed_roles = ('manager', 'sales')
    template_name = 'finance/transactions/collection.html'
    form_class = CustomerCollectionForm
    success_url = reverse_lazy('finance:collection_create')
    paginate_by = 30

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        customer_id = self.request.GET.get('customer')
        if customer_id:
            initial['customer'] = customer_id
        return initial

    def get_collection_queryset(self):
        visible_customers = visible_customers_for_user(
            self.request.user,
            Customer.objects.all(),
        )
        queryset = PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN,
            related_customer__in=visible_customers,
        ).select_related(
            'related_customer',
            'related_order',
            'cash_account',
            'created_by',
        ).order_by('-transaction_date', '-transaction_time', '-pk')

        customer_id = self.request.GET.get('customer', '').strip()
        cash_account_id = self.request.GET.get('cash_account', '').strip()
        query = self.request.GET.get('q', '').strip()

        if customer_id.isdigit():
            queryset = queryset.filter(related_customer_id=customer_id)
        if cash_account_id.isdigit():
            queryset = queryset.filter(cash_account_id=cash_account_id)
        queryset, self.date_filter = filter_by_date_period(queryset, self.request.GET, 'transaction_date')
        if query:
            queryset = queryset.filter(
                Q(related_customer__name__icontains=query)
                | Q(reference__icontains=query)
                | Q(notes__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_collection_queryset()
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        paginator = Paginator(queryset, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get('page'))
        query_params = self.request.GET.copy()
        query_params.pop('page', None)

        form = context['form']
        context.update({
            'collections': page_obj.object_list,
            'page_obj': page_obj,
            'paginator': paginator,
            'is_paginated': page_obj.has_other_pages(),
            'pagination_query': query_params.urlencode(),
            'total_amount': total_amount,
            'filter_customers': form.fields['customer'].queryset,
            'filter_cash_accounts': CashAccount.objects.filter(is_active=True).order_by('name'),
            'filters': {
                'customer': self.request.GET.get('customer', ''),
                'cash_account': self.request.GET.get('cash_account', ''),
                'date_from': self.request.GET.get('date_from', ''),
                'date_to': self.request.GET.get('date_to', ''),
                'q': self.request.GET.get('q', ''),
            },
            'invoice_section': 'receipts',
            'period_choices': PERIOD_CHOICES,
            'date_filter': getattr(self, 'date_filter', {}),
        })
        return context

    def form_valid(self, form):
        try:
            order = form.cleaned_data.get('order')
            cash_account = form.cleaned_data.get('cash_account')
            allowed_discount = form.cleaned_data.get('allowed_discount') or 0
            if order:
                amount = form.cleaned_data['amount']
                collect_order_payment(
                    order=order,
                    amount=amount,
                    user=self.request.user,
                    cash_account=cash_account,
                    notes=form.cleaned_data.get('notes') or '',
                    transaction_date=form.cleaned_data.get('transaction_date'),
                )
                if allowed_discount and amount > 0:
                    record_customer_allowed_discount(
                        order=order,
                        customer=order.customer,
                        amount=allowed_discount,
                        user=self.request.user,
                        cash_account=cash_account,
                        notes=form.cleaned_data.get('notes') or '',
                        transaction_date=form.cleaned_data.get('transaction_date'),
                    )
                    order.remaining_amount = max(order.remaining_amount - allowed_discount, 0)
                    order.payment_status = order.PAYMENT_PAID if order.remaining_amount == 0 else order.PAYMENT_PARTIAL
                    order.save(update_fields=['remaining_amount', 'payment_status'])
            else:
                amount = form.cleaned_data['amount']
                if amount < 0:
                    record_customer_refund_payment(
                        customer=form.cleaned_data.get('customer'),
                        amount=abs(amount),
                        user=self.request.user,
                        cash_account=cash_account,
                        notes=form.cleaned_data.get('notes') or '',
                        transaction_date=form.cleaned_data.get('transaction_date'),
                    )
                else:
                    collect_customer_balance_payment(
                        customer=form.cleaned_data.get('customer'),
                        amount=amount,
                        user=self.request.user,
                        cash_account=cash_account,
                        notes=form.cleaned_data.get('notes') or '',
                        transaction_date=form.cleaned_data.get('transaction_date'),
                    )
                if allowed_discount:
                    record_customer_allowed_discount(
                        customer=form.cleaned_data.get('customer'),
                        amount=allowed_discount,
                        user=self.request.user,
                        cash_account=cash_account,
                        notes=form.cleaned_data.get('notes') or '',
                        transaction_date=form.cleaned_data.get('transaction_date'),
                    )
            messages.success(self.request, 'تم تسجيل التحصيل')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class ExpenseUpdateView(ManagerRequiredMixin, FormView):
    template_name = 'finance/transactions/expense_edit.html'
    form_class = ExpenseForm
    success_url = reverse_lazy('finance:transactions')

    def get_object(self):
        return get_object_or_404(
            PaymentTransaction.objects.select_related('cash_account'),
            pk=self.kwargs['pk'],
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT,
        )

    def get_initial(self):
        initial = super().get_initial()
        expense = self.get_object()
        transaction_datetime = datetime.combine(expense.transaction_date, expense.transaction_time)
        if timezone.is_naive(transaction_datetime):
            transaction_datetime = timezone.make_aware(transaction_datetime, timezone.get_current_timezone())
        initial.update({
            'cash_account': expense.cash_account_id,
            'amount': expense.amount,
            'transaction_date': transaction_datetime,
            'notes': expense.notes or '',
        })
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['expense'] = self.get_object()
        return context

    def form_valid(self, form):
        try:
            replace_expense(
                payment_transaction=self.get_object(),
                amount=form.cleaned_data['amount'],
                cash_account=form.cleaned_data['cash_account'],
                transaction_date=form.cleaned_data['transaction_date'],
                notes=form.cleaned_data.get('notes') or '',
                user=self.request.user,
            )
            messages.success(self.request, 'تم تعديل سند الصرف وإعادة احتساب أثره المالي')
            return redirect(f"{self.success_url}?type={PaymentTransaction.TYPE_EXPENSE}")
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class CustomerCollectionUpdateView(RoleRequiredMixin, FormView):
    allowed_roles = ('manager', 'sales')
    template_name = 'finance/transactions/collection_edit.html'
    form_class = CustomerPaymentEditForm
    success_url = reverse_lazy('finance:collection_create')

    def get_object(self):
        queryset = PaymentTransaction.objects.select_related(
            'related_customer',
            'cash_account',
            'related_order',
        )
        if not self.request.user.is_manager:
            queryset = queryset.filter(created_by=self.request.user)
        return get_object_or_404(
            queryset,
            pk=self.kwargs['pk'],
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN,
            related_customer__isnull=False,
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        payment = self.get_object()
        transaction_datetime = datetime.combine(
            payment.transaction_date,
            payment.transaction_time,
        )
        if timezone.is_naive(transaction_datetime):
            transaction_datetime = timezone.make_aware(
                transaction_datetime,
                timezone.get_current_timezone(),
            )
        initial.update({
            'customer': payment.related_customer_id,
            'amount': payment.amount,
            'cash_account': payment.cash_account_id,
            'transaction_date': transaction_datetime,
            'notes': payment.notes or '',
        })
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payment'] = self.get_object()
        return context

    def form_valid(self, form):
        try:
            replace_customer_payment(
                payment_transaction=self.get_object(),
                customer=form.cleaned_data['customer'],
                amount=form.cleaned_data['amount'],
                cash_account=form.cleaned_data['cash_account'],
                transaction_date=form.cleaned_data['transaction_date'],
                notes=form.cleaned_data.get('notes') or '',
                user=self.request.user,
            )
            messages.success(self.request, 'تم تعديل عملية القبض وإعادة احتساب أثرها المالي')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class TransferView(RoleRequiredMixin, FormView):
    allowed_roles = ('manager', 'sales', 'warehouse')
    template_name = 'finance/transactions/transfer.html'
    form_class = TransferForm
    success_url = reverse_lazy('finance:transactions')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            transfer_between_accounts(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم التحويل بين الخزن')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, _validation_error_message(exc))
            return self.form_invalid(form)


class SupplierPaymentView(ManagerRequiredMixin, FormView):
    template_name = 'finance/transactions/supplier_payment.html'
    form_class = SupplierPaymentForm
    success_url = reverse_lazy('finance:cash')

    def form_valid(self, form):
        try:
            supplier = form.cleaned_data['supplier']
            amount = form.cleaned_data['amount']
            record_supplier_payment(
                supplier=supplier,
                amount=amount,
                user=self.request.user,
                cash_account=form.cleaned_data.get('cash_account'),
                notes=form.cleaned_data.get('notes') or f'دفع للمورد {supplier.name}',
                transaction_date=form.cleaned_data.get('transaction_date'),
            )
            messages.success(self.request, 'تم تسجيل الدفع للمورد')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, getattr(exc, 'message', str(exc)))
            return self.form_invalid(form)


class ShiftCloseView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/shift_close.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        default_account = CashAccount.get_default()
        
        # الحصول على معاملات اليوم
        transactions = PaymentTransaction.objects.filter(
            cash_account=default_account,
            transaction_date=today
        )
        
        # حساب الإحصائيات
        total_sales = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            direction=PaymentTransaction.DIRECTION_IN
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        total_refunds = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_REFUND,
            direction=PaymentTransaction.DIRECTION_OUT
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        total_expenses = transactions.filter(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
            direction=PaymentTransaction.DIRECTION_OUT
        ).aggregate(v=Sum('amount'))['v'] or 0
        
        expected_cash = total_sales - total_refunds - total_expenses
        
        context.update({
            'shift_start': '09:00',  # يمكن تحسينه لاحقاً من تاريخ تسجيل الدخول
            'now': timezone.now(),
            'total_sales': total_sales,
            'total_refunds': total_refunds,
            'total_expenses': total_expenses,
            'expected_cash': expected_cash,
        })
        return context


class CustomerStatementView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/statements/customer.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer_id = self.request.GET.get('customer')
        customer = None
        statement_data = {
            'entries': [],
            'total_debit': 0,
            'total_credit': 0,
            'current_balance': 0,
            'orders_balance': 0,
            'statement_opening_balance': 0,
            'remaining_opening_balance': 0,
            'opening_balance': 0,
        }
        if customer_id:
            from customers.models import Customer

            try:
                customer = Customer.objects.select_related('created_by').filter(pk=customer_id).first()
            except (TypeError, ValueError):
                customer = None
            if customer:
                statement_data = build_customer_statement(customer)
        context['customer'] = customer
        context['statement'] = statement_data['entries']
        context['total_debit'] = statement_data['total_debit']
        context['total_credit'] = statement_data['total_credit']
        context['current_balance'] = statement_data['current_balance']
        context['orders_balance'] = statement_data['orders_balance']
        context['statement_opening_balance'] = statement_data['statement_opening_balance']
        context['remaining_opening_balance'] = statement_data['remaining_opening_balance']
        context['opening_balance'] = statement_data['opening_balance']
        context['customer_id'] = customer_id or ''
        return context


class SalesRepStatementView(ManagerRequiredMixin, FormView):
    template_name = 'finance/statements/sales_rep.html'
    form_class = SalesRepStatementForm

    def form_valid(self, form):
        sales_rep = form.cleaned_data['sales_rep']
        transactions = PaymentTransaction.objects.filter(related_sales_rep=sales_rep).select_related('cash_account', 'related_order')
        return self.render_to_response(self.get_context_data(form=form, sales_rep=sales_rep, transactions=transactions))


class CashAccountStatementView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/statements/cash_account.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request_data = self.request.GET.copy()
        if request_data.get('account') and not request_data.get('cash_account'):
            request_data['cash_account'] = request_data['account']
        default_account = CashAccount.get_cash_drawer()
        form = CashAccountStatementForm(request_data or None, initial={'cash_account': default_account})
        account = None
        statement_data = {
            'entries': [],
            'opening_balance': 0,
            'current_balance': 0,
            'total_in': 0,
            'total_out': 0,
            'net_movement': 0,
            'transactions_count': 0,
            'non_cash_transactions_count': 0,
        }
        if request_data and form.is_valid():
            account = form.cleaned_data['cash_account']
            statement_data = build_cash_account_statement(account)
        elif not request_data and default_account:
            account = default_account
            statement_data = build_cash_account_statement(account)
        context.update({
            'form': form,
            'account': account,
            'statement': statement_data['entries'],
            'opening_balance': statement_data['opening_balance'],
            'current_balance': statement_data['current_balance'],
            'total_in': statement_data['total_in'],
            'total_out': statement_data['total_out'],
            'net_movement': statement_data['net_movement'],
            'transactions_count': statement_data['transactions_count'],
            'non_cash_transactions_count': statement_data['non_cash_transactions_count'],
        })
        return context


class DailyCollectionsReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/reports/daily_collections.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        transactions = PaymentTransaction.objects.filter(
            transaction_date=today,
            direction=PaymentTransaction.DIRECTION_IN,
        ).select_related('cash_account', 'related_customer', 'related_order')
        context['transactions'] = transactions
        context['total'] = transactions.aggregate(v=Sum('amount'))['v'] or 0
        return context


class ExpenseReportView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/reports/expenses.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transactions = PaymentTransaction.objects.filter(
            transaction_type=PaymentTransaction.TYPE_EXPENSE,
        ).select_related('cash_account', 'created_by')
        context['transactions'] = transactions[:100]
        context['total'] = transactions.aggregate(v=Sum('amount'))['v'] or 0
        return context
