# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2018-02-06 15:57
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('foia', '0043_communicationmovelog'),
    ]

    operations = [
        migrations.CreateModel(
            name='TrackingNumber',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tracking_id', models.CharField(blank=True, max_length=255)),
                ('datetime', models.DateTimeField(default=django.utils.timezone.now)),
                ('reason', models.CharField(choices=[(b'initial', b'Initial'), (b'appeal', b'Appeal'), (b'agency', b'New agency'), (b'other', b'Other')], max_length=7)),
            ],
            options={
                'ordering': ['-datetime'],
            },
        ),
        migrations.AlterModelOptions(
            name='foiarequest',
            options={'ordering': ['title'], 'permissions': (('view_foiarequest', 'Can view this request'), ('embargo_foiarequest', 'Can embargo request to make it private'), ('embargo_perm_foiarequest', 'Can embargo a request permananently'), ('crowdfund_foiarequest', 'Can start a crowdfund campaign for the request'), ('appeal_foiarequest', 'Can appeal the requests decision'), ('thank_foiarequest', 'Can thank the FOI officer for their help'), ('flag_foiarequest', 'Can flag the request for staff attention'), ('followup_foiarequest', 'Can send a manual follow up'), ('agency_reply_foiarequest', 'Can send a direct reply'), ('upload_attachment_foiarequest', 'Can upload an attachment'), ('export_csv', 'Can export a CSV of search results'), ('zip_download', 'Can download a zip file of all communications and files')), 'verbose_name': 'FOIA Request'},
        ),
        migrations.AlterField(
            model_name='foiarequest',
            name='multirequest',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='foias', to='foia.FOIAMultiRequest'),
        ),
        migrations.AddField(
            model_name='trackingnumber',
            name='foia',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracking_ids', to='foia.FOIARequest'),
        ),
    ]