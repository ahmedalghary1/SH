from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView

from accounts.permissions import ManagerRequiredMixin, can_view_costs, SalesRequiredMixin
from config.exports import ExportListMixin

from .forms import CashAccountForm, CustomerCollectionForm, ExpenseForm, SalesRepStatementForm, TransferForm, SupplierPaymentForm
from .models import CashAccount, PaymentTransaction
from .services import add_expense, collect_order_payment, record_customer_payment, transfer_between_accounts


class CashDashboardView(ManagerRequiredMixin, TemplateView):
    template_name = 'finance/cash.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        default_account = CashAccount.get_default()
        
        # الحصول على المعاملات اليومية
        transactions = PaymentTransaction.objects.filter(
            cash_account=default_account,
            transaction_date=today
        ).select_related('created_by').order_by('-created_at')
        
        # حساب الإحصائيات
        opening_balance = 0
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
        
        total_in = transactions.filter(direction=PaymentTransaction.DIRECTION_IN).aggregate(v=Sum('amount'))['v'] or 0
        total_out = transactions.filter(direction=PaymentTransaction.DIRECTION_OUT).aggregate(v=Sum('amount'))['v'] or 0
        current_balance = default_account.balance
        
        context.update({
            'opening_balance': opening_balance,
            'cash_sales': cash_sales,
            'customer_collections': customer_collections,
            'supplier_payments': supplier_payments,
            'expenses': expenses,
            'cash_refunds': cash_refunds,
            'current_balance': current_balance,
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
        date_from = parse_date(self.request.GET.get('date_from', ''))
        date_to = parse_date(self.request.GET.get('date_to', ''))
        if date_from:
            qs = qs.filter(transaction_date__gte=date_from)
        if date_to:
            qs = qs.filter(transaction_date__lte=date_to)
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
        return context


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
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class CustomerCollectionView(ManagerRequiredMixin, FormView):
    template_name = 'finance/transactions/collection.html'
    form_class = CustomerCollectionForm
    success_url = reverse_lazy('finance:transactions')

    def form_valid(self, form):
        try:
            order = form.cleaned_data.get('order')
            if order:
                collect_order_payment(
                    order=order,
                    amount=form.cleaned_data['amount'],
                    cash_account=form.cleaned_data['cash_account'],
                    user=self.request.user,
                    notes=form.cleaned_data.get('notes') or '',
                    transaction_date=form.cleaned_data.get('transaction_date'),
                )
            else:
                record_customer_payment(
                    order=None,
                    customer=form.cleaned_data.get('customer'),
                    amount=form.cleaned_data['amount'],
                    cash_account=form.cleaned_data['cash_account'],
                    user=self.request.user,
                    notes=form.cleaned_data.get('notes') or '',
                    transaction_date=form.cleaned_data.get('transaction_date'),
                )
            messages.success(self.request, 'تم تسجيل التحصيل')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class TransferView(ManagerRequiredMixin, FormView):
    template_name = 'finance/transactions/transfer.html'
    form_class = TransferForm
    success_url = reverse_lazy('finance:transactions')

    def form_valid(self, form):
        try:
            transfer_between_accounts(user=self.request.user, **form.cleaned_data)
            messages.success(self.request, 'تم التحويل بين الخزن')
            return redirect(self.success_url)
        except ValidationError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)


class SupplierPaymentView(ManagerRequiredMixin, FormView):
    template_name = 'finance/transactions/supplier_payment.html'
    form_class = SupplierPaymentForm
    success_url = reverse_lazy('finance:cash')

    def form_valid(self, form):
        try:
            supplier = form.cleaned_data['supplier']
            amount = form.cleaned_data['amount']
            cash_account = form.cleaned_data['cash_account']
            
            # إنشاء معاملة دفع للمورد
            PaymentTransaction.objects.create(
                transaction_type=PaymentTransaction.TYPE_SUPPLIER_PAYMENT,
                direction=PaymentTransaction.DIRECTION_OUT,
                amount=amount,
                cash_account=cash_account,
                related_supplier=supplier,
                related_supplier_name=supplier.name,
                notes=form.cleaned_data.get('notes') or f'دفع للمورد {supplier.name}',
                transaction_date=form.cleaned_data.get('transaction_date'),
                created_by=self.request.user,
            )
            
            # تحديث رصيد الخزنة
            cash_account.balance -= amount
            cash_account.save()
            
            messages.success(self.request, 'تم تسجيل الدفع للمورد')
            return redirect(self.success_url)
        except Exception as exc:
            form.add_error(None, str(exc))
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
        transactions = PaymentTransaction.objects.select_related('related_customer', 'related_order', 'cash_account')
        if customer_id:
            transactions = transactions.filter(related_customer_id=customer_id)
        context['transactions'] = transactions[:100]
        context['customer_id'] = customer_id or ''
        return context


class SalesRepStatementView(ManagerRequiredMixin, FormView):
    template_name = 'finance/statements/sales_rep.html'
    form_class = SalesRepStatementForm

    def form_valid(self, form):
        sales_rep = form.cleaned_data['sales_rep']
        transactions = PaymentTransaction.objects.filter(related_sales_rep=sales_rep).select_related('cash_account', 'related_order')
        return self.render_to_response(self.get_context_data(form=form, sales_rep=sales_rep, transactions=transactions))


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
