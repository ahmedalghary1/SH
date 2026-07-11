from django.test import TestCase

from accounts.models import SubmissionReceipt, User


class SubmissionReceiptTests(TestCase):
    def test_token_is_unique(self):
        user = User.objects.create_user(username='token-user', password='x')
        SubmissionReceipt.objects.create(token='same-token', user=user, path='/test/')
        with self.assertRaises(Exception):
            SubmissionReceipt.objects.create(token='same-token', user=user, path='/test/')
