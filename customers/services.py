from datetime import timedelta
from decimal import Decimal

from django.db.models import Case, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from finance.models import PaymentTransaction
from orders.models import Order
from returns.models import SalesReturn

from .models import Customer, CustomerInteraction


ACTIVE_ORDER_STATUSES = [
    Order.STATUS_CONFIRMED,
    Order.STATUS_PREPARING,
    Order.STATUS_READY,
    Order.STATUS_COMPLETED,
    Order.STATUS_PARTIALLY_RETURNED,
]


def annotate_customer_balances(queryset):
    """Annotate the authoritative balance without mutating opening balance."""
    money = DecimalField(max_digits=16, decimal_places=2)
    order_balances = Order.objects.filter(
        customer=OuterRef('pk'),
        status__in=ACTIVE_ORDER_STATUSES,
    ).values('customer').annotate(value=Sum('remaining_amount')).values('value')
    ledger_balances = PaymentTransaction.objects.filter(
        related_customer=OuterRef('pk'),
        affects_customer_balance=True,
    ).values('related_customer').annotate(
        value=Sum(Case(
            When(
                transaction_type=PaymentTransaction.TYPE_CUSTOMER_ALLOWED_DISCOUNT,
                then=-F('amount'),
            ),
            When(direction=PaymentTransaction.DIRECTION_OUT, then=F('amount')),
            When(direction=PaymentTransaction.DIRECTION_IN, then=-F('amount')),
            default=Value(0),
            output_field=money,
        )),
    ).values('value')
    return queryset.annotate(
        open_order_balance=Coalesce(Subquery(order_balances, output_field=money), Value(0), output_field=money),
        customer_ledger_delta=Coalesce(Subquery(ledger_balances, output_field=money), Value(0), output_field=money),
    ).annotate(
        current_balance=F('opening_balance') + F('open_order_balance') + F('customer_ledger_delta'),
    )


def visible_customers_for_user(user, queryset=None):
    queryset = queryset if queryset is not None else Customer.objects.all()
    if not user or getattr(user, 'is_superuser', False) or getattr(user, 'is_manager', False):
        return queryset
    if getattr(user, 'role', None) == 'sales':
        return queryset.filter(Q(sales_representative__isnull=True) | Q(sales_representative=user))
    return queryset


def _customer_orders(customer):
    return Order.objects.filter(
        customer=customer,
        document_type=Order.DOCUMENT_SALE,
    ).exclude(status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED])


def get_customer_summary(customer):
    orders_qs = _customer_orders(customer)

    order_agg = orders_qs.aggregate(
        total_purchases=Sum('total'),
        total_remaining=Sum('remaining_amount'),
    )
    total_purchases = order_agg['total_purchases'] or Decimal('0')
    orders_remaining = order_agg['total_remaining'] or Decimal('0')
    ledger_delta = PaymentTransaction.objects.filter(
        related_customer=customer,
        affects_customer_balance=True,
    ).aggregate(value=Sum(Case(
        When(transaction_type=PaymentTransaction.TYPE_CUSTOMER_ALLOWED_DISCOUNT, then=-F('amount')),
        When(direction=PaymentTransaction.DIRECTION_OUT, then=F('amount')),
        When(direction=PaymentTransaction.DIRECTION_IN, then=-F('amount')),
        default=Value(0),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )))['value'] or Decimal('0')
    total_remaining = customer.opening_balance + orders_remaining + ledger_delta

    total_paid = PaymentTransaction.objects.filter(
        related_customer=customer,
        direction=PaymentTransaction.DIRECTION_IN,
        affects_cash=True,
        transaction_type__in=[PaymentTransaction.TYPE_CUSTOMER_PAYMENT, PaymentTransaction.TYPE_SALES_REP_COLLECTION],
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    last_order = _customer_orders(customer).order_by('-created_at').first()
    last_payment = PaymentTransaction.objects.filter(
        related_customer=customer,
        direction=PaymentTransaction.DIRECTION_IN,
        affects_cash=True,
        transaction_type__in=[
            PaymentTransaction.TYPE_CUSTOMER_PAYMENT,
            PaymentTransaction.TYPE_SALES_REP_COLLECTION,
        ],
    ).order_by('-transaction_date', '-transaction_time', '-pk').first()

    interactions = customer.interactions.order_by('-created_at')
    last_interaction = interactions.first()
    next_follow_up = customer.interactions.filter(
        is_completed=False,
        next_follow_up_date__isnull=False,
    ).order_by('next_follow_up_date', 'created_at').first()

    orders_count = orders_qs.count()
    returns_count = SalesReturn.objects.filter(customer=customer, status=SalesReturn.STATUS_COMPLETED).count() if orders_count else 0
    return_rate = (Decimal(returns_count) / Decimal(orders_count) * Decimal('100')) if orders_count else Decimal('0')

    complaints_count = customer.interactions.filter(interaction_type=CustomerInteraction.TYPE_COMPLAINT, is_completed=False).count()

    return {
        'total_purchases': total_purchases,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
        'last_order': last_order,
        'last_payment': last_payment,
        'last_interaction': last_interaction,
        'next_follow_up': next_follow_up,
        'return_rate': return_rate,
        'complaints_count': complaints_count,
    }


def get_inactive_customers(days=90, user=None):
    cutoff = timezone.now() - timedelta(days=days)
    active_customer_ids = Order.objects.filter(created_at__gte=cutoff).exclude(status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED]).values('customer_id')
    qs = Customer.objects.filter(is_active=True)
    qs = visible_customers_for_user(user, qs)
    return qs.exclude(id__in=active_customer_ids).order_by('name')


def get_customers_with_debt(user=None):
    qs = annotate_customer_balances(Customer.objects.all()).filter(current_balance__gt=0)
    qs = visible_customers_for_user(user, qs)
    return qs.distinct().order_by('name')


def get_top_customers(limit=10, user=None):
    qs = Customer.objects.annotate(
        purchases_total=Sum(
            'order__total',
            filter=~Q(order__status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED]),
        )
    ).filter(purchases_total__gt=0)
    qs = visible_customers_for_user(user, qs)
    return qs.order_by('-purchases_total')[:limit]


def get_due_followups(user=None):
    today = timezone.localdate()
    qs = CustomerInteraction.objects.select_related('customer', 'created_by').filter(
        next_follow_up_date__lte=today,
        is_completed=False,
    )
    if user and not getattr(user, 'is_superuser', False) and not getattr(user, 'is_manager', False) and getattr(user, 'role', None) == 'sales':
        qs = qs.filter(Q(customer__sales_representative__isnull=True) | Q(customer__sales_representative=user))
    return qs.order_by('next_follow_up_date', '-created_at')


def get_open_complaints(user=None):
    qs = CustomerInteraction.objects.select_related('customer', 'created_by').filter(
        interaction_type=CustomerInteraction.TYPE_COMPLAINT,
        is_completed=False,
    )
    if user and not getattr(user, 'is_superuser', False) and not getattr(user, 'is_manager', False) and getattr(user, 'role', None) == 'sales':
        qs = qs.filter(Q(customer__sales_representative__isnull=True) | Q(customer__sales_representative=user))
    return qs.order_by('next_follow_up_date', '-created_at')


def get_crm_dashboard_context(user=None):
    customers_qs = visible_customers_for_user(user, Customer.objects.all())
    inactive_qs = get_inactive_customers(user=user)
    debtors_qs = get_customers_with_debt(user=user)
    due_followups = get_due_followups(user=user)
    open_complaints = get_open_complaints(user=user)
    recent_interactions = CustomerInteraction.objects.select_related('customer', 'created_by')
    if user and not getattr(user, 'is_superuser', False) and not getattr(user, 'is_manager', False) and getattr(user, 'role', None) == 'sales':
        recent_interactions = recent_interactions.filter(Q(customer__sales_representative__isnull=True) | Q(customer__sales_representative=user))
    return {
        'customers_count': customers_qs.count(),
        'active_customers_count': customers_qs.filter(is_active=True).count(),
        'inactive_customers_count': inactive_qs.count(),
        'debtors_count': debtors_qs.count(),
        'due_followups_count': due_followups.count(),
        'open_complaints_count': open_complaints.count(),
        'top_customers': get_top_customers(5, user=user),
        'recent_interactions': recent_interactions.order_by('-created_at')[:10],
        'due_followups': due_followups[:10],
    }
