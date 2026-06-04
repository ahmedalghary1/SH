from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView

from accounts.permissions import ManagerRequiredMixin

from .forms import CashAccountForm, CustomerCollectionForm, ExpenseForm, SalesRepStatementForm, TransferForm
from .models import CashAccount, PaymentTransaction
from .services import add_expense, collect_order_payment, record_customer_payment, transfer_between_accounts


class CashAccountListView(ManagerRequiredMixin, ListView):
    model = CashAccount
    template_name = 'finance/accounts/list.html'
    context_object_name = 'accounts'
    paginate_by = 20

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['transactions'] = self.object.transactions.select_related(
            'related_order', 'related_customer', 'related_sales_rep', 'created_by'
        )[:50]
        return context


class TransactionListView(ManagerRequiredMixin, ListView):
    model = PaymentTransaction
    template_name = 'finance/transactions/list.html'
    context_object_name = 'transactions'
    paginate_by = 30

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
        return qs


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
                )
            else:
                record_customer_payment(
                    order=None,
                    customer=form.cleaned_data.get('customer'),
                    amount=form.cleaned_data['amount'],
                    cash_account=form.cleaned_data['cash_account'],
                    user=self.request.user,
                    notes=form.cleaned_data.get('notes') or '',
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
            created_at__date=today,
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
