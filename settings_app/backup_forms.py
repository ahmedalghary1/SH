from django import forms

from .backup_resolution import RESOLUTIONS, STRICT
from .backup_services import limits


class BackupUploadForm(forms.Form):
    archive = forms.FileField(
        label='ملف النسخة الاحتياطية',
        widget=forms.ClearableFileInput(attrs={'accept': '.zip,application/zip'}),
    )

    def clean_archive(self):
        upload = self.cleaned_data['archive']
        if not upload.name.lower().endswith('.zip'):
            raise forms.ValidationError('اختر ملف ZIP تم تنزيله من أداة النسخ الاحتياطي بالنظام.')
        if upload.size > limits()['upload']:
            raise forms.ValidationError('حجم الملف يتجاوز الحد المسموح للرفع.')
        return upload


class BackupConfirmForm(forms.Form):
    confirm = forms.BooleanField(label='راجعت ملخص الدمج وأريد تطبيقه')
    resolution = forms.ChoiceField(choices=((STRICT, STRICT), *RESOLUTIONS),
                                   widget=forms.HiddenInput, required=False)

    def clean_resolution(self):
        return self.cleaned_data['resolution'] or STRICT


class BackupResolutionForm(forms.Form):
    resolution = forms.ChoiceField(label='معالجة التعارضات', choices=RESOLUTIONS, widget=forms.RadioSelect)


class BackupReplaceConfirmForm(forms.Form):
    saved_backup = forms.BooleanField(label='حفظت نسخة أمان من البيانات الحالية')
    confirm = forms.BooleanField(label='أوافق على الاستبدال الكامل ولدي بيانات دخول مسؤول من النسخة')
