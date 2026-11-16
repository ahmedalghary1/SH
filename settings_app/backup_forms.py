from django import forms

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
