from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from finance.models import PaymentTransaction
from orders.models import Order
from returns.models import SalesReturn

from .models import Customer, CustomerInteraction


def _customer_orders(customer):
    return Order.objects.filter(customer=customer).exclude(status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED])


def get_customer_total_purchases(customer):
    return _customer_orders(customer).aggregate(total=Sum('total'))['total'] or Decimal('0')


def get_customer_total_paid(customer):
    return PaymentTransaction.objects.filter(
        related_customer=customer,
        direction=PaymentTransaction.DIRECTION_IN,
        transaction_type__in=[PaymentTransaction.TYPE_CUSTOMER_PAYMENT, PaymentTransaction.TYPE_SALES_REP_COLLECTION],
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')


def get_customer_total_remaining(customer):
    orders_remaining = _customer_orders(customer).aggregate(total=Sum('remaining_amount'))['total'] or Decimal('0')
    return customer.opening_balance + orders_remaining


def get_customer_last_order(customer):
    return Order.objects.filter(customer=customer).exclude(status=Order.STATUS_CANCELLED).order_by('-created_at').first()


def get_customer_last_interaction(customer):
    return customer.interactions.order_by('-created_at').first()


def get_customer_next_follow_up(customer):
    return customer.interactions.filter(
        is_completed=False,
        next_follow_up_date__isnull=False,
    ).order_by('next_follow_up_date', 'created_at').first()


def get_customer_return_rate(customer):
    orders_count = _customer_orders(customer).count()
    if orders_count == 0:
        return Decimal('0')
    returns_count = SalesReturn.objects.filter(customer=customer, status=SalesReturn.STATUS_COMPLETED).count()
    return (Decimal(returns_count) / Decimal(orders_count)) * Decimal('100')


def get_customer_complaints_count(customer):
    return customer.interactions.filter(interaction_type=CustomerInteraction.TYPE_COMPLAINT, is_completed=False).count()


def get_customer_summary(customer):
    return {
        'total_purchases': get_customer_total_purchases(customer),
        'total_paid': get_customer_total_paid(customer),
        'total_remaining': get_customer_total_remaining(customer),
        'last_order': get_customer_last_order(customer),
        'last_interaction': get_customer_last_interaction(customer),
        'next_follow_up': get_customer_next_follow_up(customer),
        'return_rate': get_customer_return_rate(customer),
        'complaints_count': get_customer_complaints_count(customer),
    }


def get_inactive_customers(days=90):
    cutoff = timezone.now() - timedelta(days=days)
    active_customer_ids = Order.objects.filter(created_at__gte=cutoff).exclude(status=Order.STATUS_CANCELLED).values('customer_id')
    return Customer.objects.filter(is_active=True).exclude(id__in=active_customer_ids).order_by('name')


def get_customers_with_debt():
    return Customer.objects.filter(
        Q(opening_balance__gt=0) | Q(order__remaining_amount__gt=0)
    ).distinct().order_by('name')


def get_top_customers(limit=10):
    return Customer.objects.annotate(
        purchases_total=Sum(
            'order__total',
            filter=~Q(order__status__in=[Order.STATUS_DRAFT, Order.STATUS_CANCELLED, Order.STATUS_RETURNED]),
        )
    ).filter(purchases_total__gt=0).order_by('-purchases_total')[:limit]


def get_due_followups():
    today = timezone.localdate()
    return CustomerInteraction.objects.select_related('customer', 'created_by').filter(
        next_follow_up_date__lte=today,
        is_completed=False,
    ).order_by('next_follow_up_date', '-created_at')


def get_open_complaints():
    return CustomerInteraction.objects.select_related('customer', 'created_by').filter(
        interaction_type=CustomerInteraction.TYPE_COMPLAINT,
        is_completed=False,
    ).order_by('next_follow_up_date', '-created_at')


def get_crm_dashboard_context():
    inactive_qs = get_inactive_customers()
    debtors_qs = get_customers_with_debt()
    due_followups = get_due_followups()
    open_complaints = get_open_complaints()
    return {
        'customers_count': Customer.objects.count(),
        'active_customers_count': Customer.objects.filter(is_active=True).count(),
        'inactive_customers_count': inactive_qs.count(),
        'debtors_count': debtors_qs.count(),
        'due_followups_count': due_followups.count(),
        'open_complaints_count': open_complaints.count(),
        'top_customers': get_top_customers(5),
        'recent_interactions': CustomerInteraction.objects.select_related('customer', 'created_by').order_by('-created_at')[:10],
        'due_followups': due_followups[:10],
    }
