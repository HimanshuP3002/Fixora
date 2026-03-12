import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from celery import shared_task
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    DuplicateKeyError,
    ServerSelectionTimeoutError,
)


import requests


# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------
def get_lat_lng_from_address(address):
    try:
        query = str(address or '').strip()
        if not query:
            return None, None

        url = 'https://nominatim.openstreetmap.org/search'
        params = {'q': query, 'format': 'json', 'limit': 1}
        headers = {'User-Agent': 'Fixora-App'}

        res = requests.get(url, params=params, headers=headers, timeout=5)
        data = res.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        print('Geocoding Error:', e)
    return None, None


class AIReviewRecord(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_REVIEWED = 'reviewed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_REVIEWED, 'Reviewed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    image = models.ImageField(upload_to='ai_review/')
    predicted_label = models.CharField(max_length=120)
    confidence = models.FloatField()
    corrected_label = models.CharField(max_length=120, blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ai_review_records',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AIReviewOperation:
    MONGO_URI_TEMPLATE = "mongodb+srv://hpandey3011:<db_password>@cluster0.va3thzm.mongodb.net/?appName=Cluster0"
    DB_NAME = 'CivilOperation'
    REVIEW_COLLECTION = 'AIReviewRecords'
    TRAINING_COLLECTION = 'AITrainingDataset'
    TRAINING_VERSION_COLLECTION = 'AITrainingDatasetVersions'
    AUDIT_COLLECTION = 'AIAuditTrail'
    STATUS_PENDING = 'pending'
    STATUS_REVIEWED = 'reviewed'
    STATUS_REJECTED = 'rejected'

    def _client(self):
        return MongoClient(
            getattr(
                settings,
                'MONGO_URI',
                os.environ.get('MONGO_URI', self.MONGO_URI_TEMPLATE),
            ),
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            retryWrites=True,
        )

    def _db(self):
        return self._client()[self.DB_NAME]

    def _collections(self):
        db = self._db()
        return (
            db[self.REVIEW_COLLECTION],
            db[self.TRAINING_COLLECTION],
            db[self.TRAINING_VERSION_COLLECTION],
            db[self.AUDIT_COLLECTION],
        )

    def _serialize(self, row):
        c = float(row.get('Confidence', 0))
        return {
            'record_id': row.get('RecordID'),
            'image': row.get('Image'),
            'predicted_label': row.get('PredictedLabel'),
            'predicted_severity': row.get('PredictedSeverity'),
            'confidence': c,
            'confidence_pct': round(c * 100, 1),
            'corrected_label': row.get('CorrectedLabel', ''),
            'corrected_severity': row.get('CorrectedSeverity', ''),
            'uploaded_by': row.get('UploadedBy', 'System'),
            'status': row.get('Status', self.STATUS_PENDING),
            'ai_reasoning': row.get('AIReasoning', 'Reasoning not available.'),
            'source_issue_id': row.get('SourceIssueID', ''),
            'created_at': row.get('CreatedAt'),
            'reviewed_at': row.get('ReviewedAt'),
            'reviewer': row.get('Reviewer', ''),
            'rejection_reason': row.get('RejectionReason', ''),
            'is_low_confidence': c < 0.60,
        }

    def _dataset_version(self, training_version_coll, actor):
        version = datetime.now().strftime('v%Y%m%d.%H%M%S')
        training_version_coll.insert_one(
            {
                'Version': version,
                'CreatedAt': datetime.now(),
                'CreatedBy': actor or 'System',
            }
        )
        return version

    def _save_training_example(self, review_row, reviewer, action):
        review_coll, training_coll, training_version_coll, _ = self._collections()
        _ = review_coll
        dataset_version = self._dataset_version(training_version_coll, reviewer)

        final_label = (review_row.get('CorrectedLabel') or review_row.get('PredictedLabel') or '').strip()
        final_severity = (review_row.get('CorrectedSeverity') or review_row.get('PredictedSeverity') or '').strip()
        if not final_label or not final_severity:
            return None

        training_doc = {
            'RecordID': review_row.get('RecordID'),
            'SourceIssueID': review_row.get('SourceIssueID', ''),
            'Image': review_row.get('Image'),
            'FinalLabel': final_label,
            'FinalSeverity': final_severity,
            'PredictedLabel': review_row.get('PredictedLabel'),
            'PredictedSeverity': review_row.get('PredictedSeverity'),
            'Confidence': float(review_row.get('Confidence', 0.0) or 0.0),
            'ReviewedBy': reviewer or 'System',
            'ReviewAction': action,
            'DatasetVersion': dataset_version,
            'CreatedAt': datetime.now(),
        }

        training_coll.update_one(
            {'RecordID': training_doc['RecordID']},
            {'$set': training_doc},
            upsert=True,
        )
        return dataset_version

    def get_queue(self, confidence_min=None, confidence_max=None, category=None, status=None, page=1, page_size=20):
        review_coll, _, _, _ = self._collections()
        query = {}
        confidence_filter = {}
        if confidence_min is not None:
            confidence_filter['$gte'] = float(confidence_min)
        if confidence_max is not None:
            confidence_filter['$lte'] = float(confidence_max)
        if confidence_filter:
            query['Confidence'] = confidence_filter
        if category:
            query['PredictedLabel'] = category
        if status:
            query['Status'] = status
        try:
            page = max(int(page), 1)
        except Exception:
            page = 1
        try:
            page_size = max(min(int(page_size), 200), 1)
        except Exception:
            page_size = 20

        total = review_coll.count_documents(query)
        skip = (page - 1) * page_size
        rows = list(review_coll.find(query).sort('CreatedAt', -1).skip(skip).limit(page_size))
        total_pages = (total + page_size - 1) // page_size if total else 0
        return {
            'records': [self._serialize(row) for row in rows],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
            },
        }

    def queue_stats(self):
        review_coll, training_coll, _, _ = self._collections()
        return {
            'pending_count': review_coll.count_documents({'Status': self.STATUS_PENDING}),
            'reviewed_count': review_coll.count_documents({'Status': self.STATUS_REVIEWED}),
            'rejected_count': review_coll.count_documents({'Status': self.STATUS_REJECTED}),
            'training_rows': training_coll.count_documents({}),
        }

    def approve(self, record_id, reviewer, save_to_training=True):
        review_coll, _, _, _ = self._collections()
        review_row = review_coll.find_one_and_update(
            {'RecordID': record_id},
            {'$set': {'Status': self.STATUS_REVIEWED, 'Reviewer': reviewer, 'ReviewedAt': datetime.now()}},
            return_document=ReturnDocument.AFTER,
        )
        if not review_row:
            return {'err': 'Record not found.'}
        dataset_version = None
        if save_to_training:
            dataset_version = self._save_training_example(review_row, reviewer, action='approved')
        return {'msg': 'Prediction approved.', 'record_id': record_id, 'dataset_version': dataset_version}

    def correct(self, record_id, corrected_label, corrected_severity, reviewer, save_to_training=True):
        review_coll, _, _, _ = self._collections()
        review_row = review_coll.find_one_and_update(
            {'RecordID': record_id},
            {'$set': {
                'CorrectedLabel': corrected_label,
                'CorrectedSeverity': corrected_severity,
                'Status': self.STATUS_REVIEWED,
                'Reviewer': reviewer,
                'ReviewedAt': datetime.now(),
            }},
            return_document=ReturnDocument.AFTER,
        )
        if not review_row:
            return {'err': 'Record not found.'}
        dataset_version = None
        if save_to_training:
            dataset_version = self._save_training_example(review_row, reviewer, action='corrected')
        return {'msg': 'Prediction corrected.', 'record_id': record_id, 'dataset_version': dataset_version}

    def reject(self, record_id, reviewer, reason=''):
        review_coll, _, _, _ = self._collections()
        result = review_coll.update_one(
            {'RecordID': record_id},
            {'$set': {'Status': self.STATUS_REJECTED, 'Reviewer': reviewer, 'ReviewedAt': datetime.now(), 'RejectionReason': reason or ''}},
        )
        if not result.matched_count:
            return {'err': 'Record not found.'}
        return {'msg': 'Record rejected.', 'record_id': record_id}

    def export_approved_data(self):
        _, training_coll, _, _ = self._collections()
        rows = list(training_coll.find({}).sort('CreatedAt', -1))
        out = []
        for row in rows:
            out.append({
                'record_id': row.get('RecordID'),
                'source_issue_id': row.get('SourceIssueID', ''),
                'image': row.get('Image'),
                'final_label': row.get('FinalLabel'),
                'final_severity': row.get('FinalSeverity'),
                'predicted_label': row.get('PredictedLabel'),
                'predicted_severity': row.get('PredictedSeverity'),
                'confidence': row.get('Confidence'),
                'reviewed_by': row.get('ReviewedBy'),
                'review_action': row.get('ReviewAction'),
                'dataset_version': row.get('DatasetVersion'),
                'created_at': row.get('CreatedAt'),
            })
        return out

class SystemSettingsDocument:
    """Mongo document shape helper for system settings."""

    COLLECTION = 'SystemSettings'
    CURRENT_DOC_ID = 'current'


class SystemSettingsDAO:
    MONGO_URI_TEMPLATE = "mongodb+srv://hpandey3011:<db_password>@cluster0.va3thzm.mongodb.net/?appName=Cluster0"
    DB_NAME = 'CivilOperation'
    SETTINGS_COLLECTION = SystemSettingsDocument.COLLECTION
    CACHE_KEY = 'fixora:system_settings:v1'
    CACHE_TIMEOUT_SECONDS = 300
    DEFAULT_CONFIG = {
        'general': {'platform_name': 'Fixora', 'contact_email': 'support@fixora.local', 'system_logo': '', 'maintenance_mode': False},
        'user_management': {'allow_public_registration': True, 'authority_approval_required': True, 'default_user_role': 'Simple User'},
        'ai_system': {'auto_classification': True, 'confidence_threshold': 0.75, 'enable_ai_training_queue': True},
        'notifications': {'email_alerts': True, 'push_notifications': True},
        'festival': {
            'auto_mode': True,
            'selected_festival': '',
            'override_date': '',
            'eclipse_date': '',
            'eclipse_type': 'Chandra Grahan',
            'eclipse_start': '',
            'eclipse_end': '',
        },
    }

    def _client(self):
        return MongoClient(
            getattr(
                settings,
                'MONGO_URI',
                os.environ.get('MONGO_URI', self.MONGO_URI_TEMPLATE),
            ),
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            retryWrites=True,
        )

    def _coll(self):
        return self._client()[self.DB_NAME][self.SETTINGS_COLLECTION]

    def _merge_with_defaults(self, config):
        merged = {
            'general': dict(self.DEFAULT_CONFIG['general']),
            'user_management': dict(self.DEFAULT_CONFIG['user_management']),
            'ai_system': dict(self.DEFAULT_CONFIG['ai_system']),
            'notifications': dict(self.DEFAULT_CONFIG['notifications']),
            'festival': dict(self.DEFAULT_CONFIG['festival']),
        }
        for section in merged:
            merged[section].update((config or {}).get(section, {}))
        return merged

    def get_current_settings(self, cache_backend=None):
        if cache_backend is not None:
            cached = cache_backend.get(self.CACHE_KEY)
            if cached:
                return {'settings': cached, 'cached': True}
        doc = self._coll().find_one({'_id': SystemSettingsDocument.CURRENT_DOC_ID})
        settings_data = self._merge_with_defaults((doc or {}).get('Config', {}))
        if cache_backend is not None:
            cache_backend.set(self.CACHE_KEY, settings_data, timeout=self.CACHE_TIMEOUT_SECONDS)
        return {'settings': settings_data, 'cached': False}

    def update_settings(self, payload, actor, cache_backend=None):
        target = self._merge_with_defaults(payload)
        self._coll().update_one(
            {'_id': SystemSettingsDocument.CURRENT_DOC_ID},
            {'$set': {'Config': target, 'UpdatedAt': datetime.now(), 'UpdatedBy': actor or 'System'}},
            upsert=True,
        )
        if cache_backend is not None:
            cache_backend.set(self.CACHE_KEY, target, timeout=self.CACHE_TIMEOUT_SECONDS)
        return {'msg': 'Settings updated successfully.', 'settings': target, 'version': datetime.now().strftime('v%Y%m%d.%H%M%S')}

    def reset_defaults(self, actor, cache_backend=None):
        return self.update_settings(self.DEFAULT_CONFIG, actor=actor, cache_backend=cache_backend)


class CivilOperation:
    def _extract_issue_seq(self, issue_id):
        try:
            return int(str(issue_id).split('-')[1])
        except Exception:
            return 0

    def _max_issue_sequence(self, coll):
        max_seq = 0
        try:
            cursor = coll.find({'IssueID': {'$exists': True}}, {'IssueID': 1})
            for row in cursor:
                max_seq = max(max_seq, self._extract_issue_seq(row.get('IssueID')))
        except Exception as e:
            print('Model Error in Max Issue Sequence:', str(e))
        return max_seq

    def _sync_issue_counter(self, db, coll):
        counter_coll = db['counters']
        max_seq = self._max_issue_sequence(coll)
        counter = counter_coll.find_one({'_id': 'issue_id'})
        current_seq = int(counter.get('seq', 0)) if counter else 0
        if not counter:
            counter_coll.insert_one({'_id': 'issue_id', 'seq': max_seq})
        elif current_seq < max_seq:
            counter_coll.update_one({'_id': 'issue_id'}, {'$set': {'seq': max_seq}})

    def register_issue(self, cat, ttl, loc, desc, img, user, cont, lnd, urg, contact_e164=''):
        stat = {}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']
            self._sync_issue_counter(db, coll)

            counter = db.counters.find_one_and_update(
                {'_id': 'issue_id'},
                {'$inc': {'seq': 1}},
                upsert=True,
                return_document=True,
            )
            new_id = f"ISSUE-{str(counter['seq']).zfill(3)}"

            image_url = ''
            if img:
                fs = FileSystemStorage()
                file_extension = os.path.splitext(img.name)[1]
                unique_filename = f'Issue/{uuid.uuid4()}{file_extension}'
                saved_name = fs.save(unique_filename, img)
                image_url = fs.url(saved_name)

            lat, lng = get_lat_lng_from_address(loc)
            doc = {
                'IssueID': new_id,
                'Category': cat,
                'Title': ttl,
                'Location': loc,
                'lat': lat,
                'lng': lng,
                'Description': desc,
                'Image': image_url,
                'ReportedBy': user,
                'Contact': cont,
                'ContactE164': contact_e164,
                'Landmark': lnd,
                'Urgency': urg,
                'Status': 'Pending',
                'IssueDate': datetime.now(),
            }
            coll.create_index('IssueID', unique=True)
            coll.insert_one(doc)

            stat['msg'] = 'Issue Reported Successfully'
            stat['IssueID'] = new_id

            try:
                from main.tasks import dispatch_new_issue_notifications
            except Exception as import_err:
                dispatch_new_issue_notifications = None
                print('Notification task import failed:', str(import_err))

            if dispatch_new_issue_notifications:
                task_payload = {
                    'issue_id': new_id,
                    'title': ttl,
                    'category': cat,
                    'urgency': urg,
                    'reported_by': user,
                    'location': loc,
                    'related_link': f'/issue/{new_id}/',
                }
                try:
                    dispatch_new_issue_notifications.delay(**task_payload)
                except Exception as task_err:
                    print('Celery dispatch failed, running notification fallback:', str(task_err))
                    try:
                        dispatch_new_issue_notifications(**task_payload)
                    except Exception as fallback_err:
                        print('Notification fallback failed:', str(fallback_err))

        except Exception as e:
            stat['err'] = 'Oops! Something went wrong!'
            print('Model Error in Report Issue:', str(e))

        return stat

    def fetch_issues(self, user):
        issues = []
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']

            # Match issues by reporter identity with legacy key support.
            user_text = str(user or '').strip()
            user_pattern = {'$regex': f'^{re.escape(user_text)}$', '$options': 'i'}
            reporter_query = {
                '$or': [
                    {'ReportedBy': user_pattern},
                    {'reported_by': user_pattern},
                    {'reporter': user_pattern},
                    {'UserName': user_pattern},
                    {'EmailID': user_pattern}
                ]
            }
            issues = list(coll.find(reporter_query).sort('IssueDate', -1))

        except Exception as e:
            print('Model Error in Fetch Issues: ' + str(e))
        return issues

    def get_issue_by_id(self, issue_id):
        issue = None
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']
            
            # FIX: Query using your custom 'IssueID' string field
            # We match the variable 'issue_id' directly to the database column 'IssueID'
            issue = coll.find_one({'IssueID': issue_id})
            # print(f"Queried for IssueID: {issue_id}, Found: {issue}")

        except Exception as e:
            print('Model Error in Get Issue by ID: ' + str(e))
        return issue

    def count(self):
        stat = {
            'total_issues': 0,
            'resolved_issues': 0,
            'active_users': 0,
            'err': None
        }

        try:
            client = MongoClient(settings.MONGO_URI)

            # ---- CivilOperation DB ----
            civil_db = client['CivilOperation']
            issue_coll = civil_db['Issue']

            stat['total_issues'] = issue_coll.count_documents({})
            stat['resolved_issues'] = issue_coll.count_documents({'Status': 'Resolved'})

            # ---- User DB ----
            user_db = client['UserOperation']
            simple_user_coll = user_db['Simple_Users']
            admin_user_coll = user_db['Admin_Users']
            authority_user_coll = user_db['Authority_Users']

            # Registered users across all backend user collections
            stat['active_users'] = (
                simple_user_coll.count_documents({})
                + admin_user_coll.count_documents({})
                + authority_user_coll.count_documents({})
            )

        except Exception as e:
            print("exception:", str(e))
            stat['err'] = 'Connection Error'

        return stat

    def fetch_map_issues(self, filters=None):
        stat = {
            'msg': None,
            'err': None,
            'issues': []
        }

        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']


            query = {}

            if filters:
                # Expected keys in filters:
                # Category, Urgency, Status
                if filters.get('Category'):
                    query['Category'] = filters['Category']

                if filters.get('Urgency'):
                    query['Urgency'] = filters['Urgency']

                if filters.get('Status'):
                    query['Status'] = filters['Status']

            # Lightweight projection for map usage
            issues = list(coll.find(
                query,
                {
                    '_id': 0,
                    'IssueID': 1,
                    'Category': 1,
                    'Urgency': 1,
                    'Status': 1,
                    'Location': 1
                }
            ))

            stat['issues'] = issues
            stat['msg'] = 'Map issues fetched successfully'

        except Exception as e:
            stat['err'] = 'Oops! Something went wrong while fetching map issues'
            print('Model Error in Fetch Map Issues:', str(e))

        return stat

    def get_preview_issue_id(self):
        client = MongoClient(settings.MONGO_URI)
        db = client['CivilOperation']
        issue_coll = db['Issue']
        counter_coll = db['counters']

        self._sync_issue_counter(db, issue_coll)
        counter = counter_coll.find_one({'_id': 'issue_id'}) or {'seq': 0}
        next_number = int(counter.get('seq', 0)) + 1

        return f"ISSUE-{str(next_number).zfill(3)}"

    def fetch_all_issues(self, username, utype, limit=6):
        stat = {
            'msg': None,
            'err': None,
            'issues': []
        }

        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']

            projection = {
                '_id': 0,
                'IssueID': 1,
                'Title': 1,
                'Category': 1,
                'Urgency': 1,
                'Status': 1,
                'Location': 1,
                'Image': 1,
                'IssueDate': 1,
                'ReportedBy': 1,
                'Department': 1
            }

            # --- ADMIN: fetch all issues ---
            if utype in ['Super Admin', 'Moderator', 'Editor', 'Admin User']:
                cursor = coll.find({}, projection).sort('IssueDate', -1)
            # --- SIMPLE USER: fetch own issues ---
            else:
                username_text = str(username or '').strip()
                username_pattern = {'$regex': f'^{re.escape(username_text)}$', '$options': 'i'}
                own_query = {
                    '$or': [
                        {'ReportedBy': username_pattern},
                        {'reported_by': username_pattern},
                        {'reporter': username_pattern},
                        {'UserName': username_pattern},
                        {'EmailID': username_pattern}
                    ]
                }
                cursor = coll.find(own_query, projection).sort('IssueDate', -1)

            if isinstance(limit, int) and limit > 0:
                cursor = cursor.limit(limit)

            issues = list(cursor)

            stat['issues'] = issues
            stat['msg'] = 'Issues fetched successfully'

        except Exception as e:
            print('Model Error in Fetch All Issues:', str(e))
            stat['err'] = 'Oops! Something went wrong while fetching issues'

        return stat

    def update_issue_status(self, issue_id, new_status):
        stat = {'msg': None, 'err': None}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']

            result = coll.update_one(
                {'IssueID': issue_id},
                {'$set': {'Status': new_status}}
            )

            if result.matched_count:
                stat['msg'] = 'Status updated'
            else:
                stat['err'] = 'Issue not found'

        except Exception as e:
            stat['err'] = 'Failed to update status'
            print('Model Error in Update Issue Status:', str(e))

        return stat

    def update_issue_assignment(self, issue_id, authority):
        stat = {'msg': None, 'err': None}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']

            result = coll.update_one(
                {'IssueID': issue_id},
                {'$set': {'Department': authority}}
            )

            if result.matched_count:
                stat['msg'] = 'Assignment updated'
            else:
                stat['err'] = 'Issue not found'

        except Exception as e:
            stat['err'] = 'Failed to update assignment'
            print('Model Error in Update Issue Assignment:', str(e))

        return stat

    def get_reports_data(self, days=30, start_date=None, end_date=None, category=None, status=None):
        stat = {
            'total_reports': 0,
            'resolved_count': 0,
            'active_count': 0,
            'resolved_rate': 0,
            'avg_resolution_days': 0,
            'trend_labels': [],
            'trend_values': [],
            'category_labels': [],
            'category_values': [],
            'urgency_labels': [],
            'urgency_values': [],
            'status_labels': [],
            'status_values': [],
            'top_locations_labels': [],
            'top_locations_values': []
        }

        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['CivilOperation']
            coll = db['Issue']

            query = {}
            if category:
                query['Category'] = category
            if status:
                query['Status'] = status

            projection = {
                '_id': 0,
                'IssueDate': 1,
                'Category': 1,
                'Status': 1,
                'Urgency': 1,
                'Location': 1
            }
            issues = list(coll.find(query, projection))

            if start_date or end_date:
                filtered = []
                for i in issues:
                    issue_date = i.get('IssueDate')
                    if not isinstance(issue_date, datetime):
                        continue
                    if start_date and issue_date < start_date:
                        continue
                    if end_date and issue_date > end_date:
                        continue
                    filtered.append(i)
                issues = filtered

            total = len(issues)
            resolved = [i for i in issues if i.get('Status') == 'Resolved']
            active = [i for i in issues if i.get('Status') != 'Resolved']

            stat['total_reports'] = total
            stat['resolved_count'] = len(resolved)
            stat['active_count'] = len(active)
            stat['resolved_rate'] = round((len(resolved) / total) * 100) if total else 0

            if resolved:
                now = datetime.now()
                days_list = []
                for i in resolved:
                    issue_date = i.get('IssueDate')
                    if isinstance(issue_date, datetime):
                        days_list.append((now - issue_date).days)
                stat['avg_resolution_days'] = round(sum(days_list) / len(days_list), 1) if days_list else 0

            def count_by_key(key):
                counts = {}
                for i in issues:
                    value = i.get(key) or 'Unknown'
                    counts[value] = counts.get(value, 0) + 1
                labels = list(counts.keys())
                values = [counts[k] for k in labels]
                return labels, values

            cat_labels, cat_values = count_by_key('Category')
            urg_labels, urg_values = count_by_key('Urgency')
            status_labels, status_values = count_by_key('Status')

            stat['category_labels'] = cat_labels
            stat['category_values'] = cat_values
            stat['urgency_labels'] = urg_labels
            stat['urgency_values'] = urg_values
            stat['status_labels'] = status_labels
            stat['status_values'] = status_values

            # Trend: last N days
            start = datetime.now() - timedelta(days=max(days - 1, 1))
            trend_counts = {}
            for i in issues:
                issue_date = i.get('IssueDate')
                if isinstance(issue_date, datetime) and issue_date >= start:
                    key = issue_date.strftime('%b %d')
                    trend_counts[key] = trend_counts.get(key, 0) + 1

            if trend_counts:
                stat['trend_labels'] = list(trend_counts.keys())
                stat['trend_values'] = [trend_counts[k] for k in stat['trend_labels']]

            # Top locations
            loc_counts = {}
            for i in issues:
                loc = i.get('Location')
                if loc:
                    loc_counts[loc] = loc_counts.get(loc, 0) + 1
            if loc_counts:
                sorted_locs = sorted(loc_counts.items(), key=lambda x: x[1], reverse=True)[:6]
                stat['top_locations_labels'] = [k for k, _ in sorted_locs]
                stat['top_locations_values'] = [v for _, v in sorted_locs]

        except Exception as e:
            print('Model Error in Reports Data:', str(e))

        return stat


# ---------------------------------------------------------------------------
# User Operations
# ---------------------------------------------------------------------------
class UserOperation:
    def _normalize_legacy_admin_user_roles(self, admin_coll):
        """Backfill legacy admin docs where UserRole is still 'Admin User'."""
        try:
            legacy_docs = list(
                admin_coll.find(
                    {
                        '$or': [
                            {'UserRole': {'$exists': False}},
                            {'UserRole': ''},
                            {'UserRole': 'Admin User'}
                        ],
                        'AdminRole': {'$in': ['Super Admin', 'Moderator', 'Editor']}
                    },
                    {'_id': 1, 'AdminRole': 1}
                )
            )
            for doc in legacy_docs:
                admin_coll.update_one(
                    {'_id': doc['_id']},
                    {'$set': {'UserRole': doc.get('AdminRole')}}
                )
        except Exception as e:
            print('Model Error in Normalize Legacy Admin Roles: ' + str(e))

    def get_preview_admin_id(self):
        preview_id = "ADM-001"
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            coll = db['Admin_Users']

            last_admin = coll.find_one(sort=[("User_ID", -1)])
            if last_admin and 'User_ID' in last_admin:
                last_id_num = int(last_admin['User_ID'].split('-')[1])
                preview_id = f"ADM-{str(last_id_num + 1).zfill(3)}"
        except Exception as e:
            print('Model Error in Preview Admin ID: ' + str(e))

        return preview_id

    def get_preview_authority_id(self):
        preview_id = "AUTH_0001_VSR"
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            coll = db['Authority_Users']

            # Support both legacy User_ID and new Authority_ID records.
            candidates = []
            last_by_authority = coll.find_one({'Authority_ID': {'$exists': True}}, sort=[("Authority_ID", -1)])
            last_by_legacy = coll.find_one({'User_ID': {'$exists': True}}, sort=[("User_ID", -1)])
            if last_by_authority:
                candidates.append(last_by_authority.get('Authority_ID', ''))
            if last_by_legacy:
                candidates.append(last_by_legacy.get('User_ID', ''))

            max_num = 0
            for raw_id in candidates:
                # Expected new format: AUTH_0001_VSR
                if isinstance(raw_id, str) and raw_id.startswith('AUTH_') and raw_id.endswith('_VSR'):
                    mid = raw_id[len('AUTH_'):-len('_VSR')]
                    if mid.isdigit():
                        max_num = max(max_num, int(mid))
                        continue
                # Legacy fallback format: AUTH-001
                if isinstance(raw_id, str) and raw_id.startswith('AUTH-'):
                    parts = raw_id.split('-')
                    if len(parts) == 2 and parts[1].isdigit():
                        max_num = max(max_num, int(parts[1]))

            if max_num > 0:
                preview_id = f"AUTH_{str(max_num + 1).zfill(4)}_VSR"
        except Exception as e:
            print('Model Error in Preview Authority ID: ' + str(e))

        return preview_id

    def get_preview_employee_id(self):
        # Employee ID format for authority requests
        return self.get_preview_authority_id()

    def register_user(self, fname, user, email, pwd):
        stat = {}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            coll = db['Simple_Users']

            # Logic to generate Auto-Increment ID (USR-001)
            # We find the latest user by sorting 'User_ID' in descending order
            last_user = coll.find_one(sort=[("User_ID", -1)])
            
            if last_user and 'User_ID' in last_user:
                # Extract the number from 'USR-001', increment it
                last_id_str = last_user['User_ID'] # e.g., "USR-005"
                last_id_num = int(last_id_str.split('-')[1])
                new_id = f"USR-{str(last_id_num + 1).zfill(3)}"
            else:
                # If no users exist, start with USR-001
                new_id = "USR-001"

            dic = {}
            dic['User_ID'] = new_id  # Added the generated ID
            dic['Full_Name'] = fname
            dic['UserName'] = user
            dic['EmailID'] = email
            dic['Password'] = pwd
            dic['UserRole'] = 'Simple User'
            dic['Status'] = 'Activated'
            dic['Created_At'] = datetime.now() # Added () to call the function
            coll.create_index('UserName')
            coll.create_index('User_ID', unique=True)  # Ensure User_ID is unique
            coll.insert_one(dic)

            stat['msg'] = 'Registration Successful'

        except Exception as e:
            stat['err'] = f'Oops! Somthing went wrong.....!'
            print('Model Error in Register: '+ str(e))
        
        return stat

    def login_user(self, user, pwd):
        stat = {
            'msg' : None,
            'err' : None
        }

        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            coll_user = db['Simple_Users']
            coll_admin = db['Admin_Users']
            coll_authority = db['Authority_Users']

            self._normalize_legacy_admin_user_roles(coll_admin)

            print(user, pwd)

            # Keep direct username/password checks
            Simple_User = coll_user.find_one({'UserName': user})
            Admin_User = coll_admin.find_one({'UserName': user})

            # Authority login by email + hashed password
            pwd_hash = hashlib.sha256(pwd.encode('utf-8')).hexdigest()
            Authority_User = coll_authority.find_one({'EmailID': user, 'PasswordHash': pwd_hash})

            # Priority: admin -> simple -> authority
            existing_user = Admin_User or Simple_User or Authority_User

            # print(existing_user)

            if existing_user:
                print(existing_user)
                if existing_user['Status'] == 'Activated':
                    stat['msg'] = 'Login Successful'
                    stat['fname'] = existing_user['Full_Name']
                    stat['utype'] = (
                        existing_user.get('UserRole')
                        or existing_user.get('AdminRole')
                        or 'Simple User'
                    )
                else:
                    stat['err'] = 'Your account is deactivated.'
                    print(stat)
                    return stat
            else:
                stat['err'] = 'Invalid Username or Password.'
                        
        except Exception as e:
            print('Model Error in Login: ' + str(e))
            stat['err'] = 'Oops! Something went wrong....!'
        return stat

    def checkType(self, name):
        default_utype = None
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            user_coll = db['Simple_Users']
            admin_coll = db['Admin_Users']
            authority_coll = db['Authority_Users']

            default_utype = 'Simple User'

            self._normalize_legacy_admin_user_roles(admin_coll)

            # Prioritize admin collection so admin accounts are not treated as simple users.
            admin_user = admin_coll.find_one({'$or': [{'UserName': name}, {'EmailID': name}]})
            authority_user = authority_coll.find_one({'$or': [{'UserName': name}, {'EmailID': name}]})
            simple_user = user_coll.find_one({'$or': [{'UserName': name}, {'EmailID': name}]})

            if admin_user:
                utype = admin_user.get('UserRole') or admin_user.get('AdminRole') or 'Admin User'
            elif authority_user:
                utype = authority_user.get('UserRole', 'Authority')
            elif simple_user:
                utype = simple_user.get('UserRole', default_utype)
            else:
                print(f"No document found for Username '{name}'.")
                utype = default_utype

            print(f"The 'utype' value for Username '{name}' is: {utype}")

        except Exception as e:
            print('Model Error in CheckType: ' + str(e))
            utype = default_utype

        return utype

    def get_admin_role(self, name):
        admin_role = ''
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            admin_coll = db['Admin_Users']

            result = admin_coll.find_one({'$or': [{'UserName': name}, {'EmailID': name}]})
            if result:
                admin_role = result.get('AdminRole', '')
                # Backward compatibility for records storing role in UserRole.
                if not admin_role:
                    legacy_role = result.get('UserRole', '')
                    if legacy_role in ['Super Admin', 'Moderator', 'Editor']:
                        admin_role = legacy_role
        except Exception as e:
            print('Model Error in Get Admin Role: ' + str(e))

        return admin_role

    def get_user_email(self, name_or_email):
        email = ''
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            simple_coll = db['Simple_Users']
            admin_coll = db['Admin_Users']
            authority_coll = db['Authority_Users']

            result = simple_coll.find_one({'UserName': name_or_email}, {'EmailID': 1})
            if not result:
                result = admin_coll.find_one({'UserName': name_or_email}, {'EmailID': 1})
            if not result:
                result = authority_coll.find_one({'EmailID': name_or_email}, {'EmailID': 1})

            if result:
                email = result.get('EmailID', '')
        except Exception as e:
            print('Model Error in Get User Email: ' + str(e))

        return email
    def ensure_social_user(self, full_name, username, email):
        profile = {
            'login_key': email,
            'full_name': full_name or username or email,
            'email': email,
            'user_role': 'Simple User',
        }

        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            simple_coll = db['Simple_Users']
            admin_coll = db['Admin_Users']
            authority_coll = db['Authority_Users']

            self._normalize_legacy_admin_user_roles(admin_coll)

            existing_simple = simple_coll.find_one({'EmailID': email})
            if existing_simple:
                profile['login_key'] = existing_simple.get('UserName') or email
                profile['full_name'] = existing_simple.get('Full_Name') or profile['full_name']
                profile['user_role'] = existing_simple.get('UserRole') or 'Simple User'
                return profile

            existing_admin = admin_coll.find_one({'EmailID': email})
            if existing_admin:
                profile['login_key'] = existing_admin.get('UserName') or email
                profile['full_name'] = existing_admin.get('Full_Name') or profile['full_name']
                profile['user_role'] = existing_admin.get('UserRole') or existing_admin.get('AdminRole') or 'Admin User'
                return profile

            existing_authority = authority_coll.find_one({'EmailID': email})
            if existing_authority:
                profile['login_key'] = existing_authority.get('UserName') or email
                profile['full_name'] = existing_authority.get('Full_Name') or profile['full_name']
                profile['user_role'] = existing_authority.get('UserRole') or 'Authority'
                return profile

            base_username = (username or email.split('@')[0] or 'fixora_user').strip().lower()
            base_username = re.sub(r'[^a-z0-9_.-]', '', base_username) or 'fixora_user'
            candidate_username = base_username
            suffix = 1
            while simple_coll.find_one({'UserName': candidate_username}) or admin_coll.find_one({'UserName': candidate_username}):
                suffix += 1
                candidate_username = f"{base_username}{suffix}"

            last_user = simple_coll.find_one(sort=[('User_ID', -1)])
            if last_user and 'User_ID' in last_user:
                last_id_num = int(str(last_user['User_ID']).split('-')[1])
                new_id = f"USR-{str(last_id_num + 1).zfill(3)}"
            else:
                new_id = 'USR-001'

            social_doc = {
                'User_ID': new_id,
                'Full_Name': full_name or candidate_username,
                'UserName': candidate_username,
                'EmailID': email,
                'Password': hashlib.sha256(os.urandom(32)).hexdigest(),
                'UserRole': 'Simple User',
                'Status': 'Activated',
                'Created_At': datetime.now(),
                'AuthProvider': 'social',
            }

            simple_coll.create_index('UserName')
            simple_coll.create_index('EmailID')
            simple_coll.create_index('User_ID', unique=True)
            simple_coll.insert_one(social_doc)

            profile['login_key'] = candidate_username
            profile['full_name'] = social_doc['Full_Name']
            profile['user_role'] = social_doc['UserRole']
            return profile

        except Exception as e:
            print('Model Error in Ensure Social User: ' + str(e))
            return profile
    def fetch_user_details(self, username):
        stat = {
            'msg': None,
            'err': None
        }
        user_details = None
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            simple_coll = db['Simple_Users']
            admin_coll = db['Admin_Users']
            authority_coll = db['Authority_Users']

            lookup = {'$or': [{'UserName': username}, {'EmailID': username}]}

            user_details = simple_coll.find_one(lookup)
            if not user_details:
                user_details = admin_coll.find_one(lookup)
            if not user_details:
                user_details = authority_coll.find_one(lookup)
            if user_details:
                stat['msg'] = 'User details fetched successfully'
                stat['user_details'] = user_details
            else:
                stat['err'] = 'User not found'
        except Exception as e:
            print('Model Error in Fetch User Details: ' + str(e))
            stat['err'] = 'Oops! Something went wrong....!'
        return stat

    def update_user_full_name(self, username, full_name):
        stat = {'msg': None, 'err': None}
        try:
            target_name = str(full_name or '').strip()
            if not target_name:
                stat['err'] = 'Full name is required.'
                return stat

            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            simple_coll = db['Simple_Users']
            admin_coll = db['Admin_Users']
            authority_coll = db['Authority_Users']

            lookup = {'$or': [{'UserName': username}, {'EmailID': username}]}
            update_doc = {'$set': {'Full_Name': target_name}}

            result = simple_coll.update_one(lookup, update_doc)
            if not result.matched_count:
                result = admin_coll.update_one(lookup, update_doc)
            if not result.matched_count:
                result = authority_coll.update_one(lookup, update_doc)

            if result.matched_count:
                stat['msg'] = 'Profile updated successfully.'
            else:
                stat['err'] = 'User not found.'
        except Exception as e:
            print('Model Error in Update User Full Name:', str(e))
            stat['err'] = 'Failed to update profile.'

        return stat

    def register_admin_user(self, fname, user, email, pwd, role, security_token, avatar=None):
        stat = {}
        try:
            if security_token != 'FIXORA-ADMIN-2026':
                stat['err'] = 'Invalid security token.'
                return stat

            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            coll = db['Admin_Users']

            last_admin = coll.find_one(sort=[("User_ID", -1)])
            if last_admin and 'User_ID' in last_admin:
                last_id_num = int(last_admin['User_ID'].split('-')[1])
                new_id = f"ADM-{str(last_id_num + 1).zfill(3)}"
            else:
                new_id = "ADM-001"

            avatar_url = ''
            if avatar:
                fs = FileSystemStorage()
                ext = os.path.splitext(avatar.name)[1]
                unique_filename = f"AdminUsers/{uuid.uuid4()}{ext}"
                saved_name = fs.save(unique_filename, avatar)
                avatar_url = fs.url(saved_name)

            doc = {
                'User_ID': new_id,
                'Full_Name': fname,
                'UserName': user,
                'EmailID': email,
                'Password': pwd,
                'UserRole': role,
                'AdminRole': role,
                'Status': 'Activated',
                'Avatar': avatar_url,
                'Created_At': datetime.now()
            }

            coll.create_index('User_ID', unique=True)
            coll.insert_one(doc)

            stat['msg'] = 'Admin user registered successfully.'
            stat['AdminID'] = new_id

        except Exception as e:
            stat['err'] = 'Oops! Somthing went wrong.....!'
            print('Model Error in Admin Registration: ' + str(e))

        return stat

    def register_authority_user(
        self,
        full_name,
        department_name,
        official_email,
        employee_id,
        phone_country_code,
        phone_number,
        role,
        password_hash,
        phone_number_e164='',
        verification_document=None
    ):
        stat = {}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            coll = db['Authority_Users']

            if coll.find_one({'EmailID': official_email}):
                stat['err'] = 'Authority email already exists.'
                return stat

            if coll.find_one({'EmployeeID': employee_id}):
                stat['err'] = 'Employee ID already exists.'
                return stat

            auth_id = self.get_preview_authority_id()

            verification_doc_url = ''
            if verification_document:
                fs = FileSystemStorage()
                ext = os.path.splitext(verification_document.name)[1]
                unique_filename = f"AuthorityRequests/{uuid.uuid4()}{ext}"
                saved_name = fs.save(unique_filename, verification_document)
                verification_doc_url = fs.url(saved_name)

            dic = {}
            dic['Authority_ID'] = auth_id
            dic['Full_Name'] = full_name
            dic['DepartmentName'] = department_name
            dic['EmailID'] = official_email
            dic['EmployeeID'] = employee_id
            dic['PhoneCountryCode'] = phone_country_code
            dic['PhoneNumber'] = phone_number
            dic['PhoneE164Like'] = phone_number_e164 or f"{phone_country_code}{phone_number}"
            dic['RequestedRole'] = role
            dic['PasswordHash'] = password_hash
            dic['UserRole'] = 'Authority'
            dic['Status'] = 'Pending Approval'
            dic['IsVerified'] = False
            dic['VerificationDocument'] = verification_doc_url
            dic['RequestType'] = 'Authority Access Request'
            dic['RequestedAt'] = datetime.now()
            dic['Created_At'] = datetime.now()

            coll.create_index('Authority_ID', unique=True)
            coll.create_index('EmailID', unique=True)
            coll.create_index('EmployeeID')
            coll.insert_one(dic)

            stat['msg'] = 'Authority access request submitted. Approval is pending.'
            stat['AuthorityID'] = auth_id

        except Exception as e:
            stat['err'] = 'Oops! Somthing went wrong.....!'
            print('Model Error in Authority Register: ' + str(e))

        return stat

    def fetch_all_users(self, search=None, role=None, status=None):
        stat = {'msg': None, 'err': None, 'users': []}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            admin_coll = db['Admin_Users']
            simple_coll = db['Simple_Users']
            authority_coll = db['Authority_Users']

            self._normalize_legacy_admin_user_roles(admin_coll)

            and_filters = []

            if role:
                and_filters.append(
                    {
                        '$or': [
                            {'UserRole': role},
                            {'AdminRole': role}
                        ]
                    }
                )

            if status:
                if status == 'Activated':
                    and_filters.append(
                        {
                            '$or': [
                                {'Status': 'Activated'},
                                {'Status': {'$exists': False}},
                                {'Status': ''}
                            ]
                        }
                    )
                elif status == 'Pending':
                    and_filters.append({'Status': {'$regex': '^Pending', '$options': 'i'}})
                else:
                    and_filters.append({'Status': status})

            if search:
                search_criteria = [
                    {'UserName': {'$regex': search, '$options': 'i'}},
                    {'Full_Name': {'$regex': search, '$options': 'i'}},
                    {'EmailID': {'$regex': search, '$options': 'i'}},
                    {'User_ID': {'$regex': search, '$options': 'i'}},
                    {'Authority_ID': {'$regex': search, '$options': 'i'}},
                    {'EmployeeID': {'$regex': search, '$options': 'i'}}
                ]
                and_filters.append({'$or': search_criteria})

            if not and_filters:
                query = {}
            elif len(and_filters) == 1:
                query = and_filters[0]
            else:
                query = {'$and': and_filters}

            admin_users = list(admin_coll.find(query))
            simple_users = list(simple_coll.find(query))
            authority_users = list(authority_coll.find(query))

            stat['users'] = admin_users + simple_users + authority_users
            stat['msg'] = 'Users fetched'

        except Exception as e:
            stat['err'] = 'Failed to fetch users'
            print('Model Error in Fetch All Users: ' + str(e))

        return stat

    def update_admin_role(self, user_id, new_role):
        stat = {'msg': None, 'err': None}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            admin_coll = db['Admin_Users']
            simple_coll = db['Simple_Users']
            authority_coll = db['Authority_Users']

            admin_result = admin_coll.update_one(
                {'$or': [{'User_ID': user_id}, {'Authority_ID': user_id}]},
                {'$set': {'AdminRole': new_role, 'UserRole': new_role}}
            )
            if admin_result.matched_count:
                stat['msg'] = 'Role updated'
            else:
                simple_result = simple_coll.update_one(
                    {'$or': [{'User_ID': user_id}, {'Authority_ID': user_id}]},
                    {'$set': {'UserRole': new_role}}
                )
                if simple_result.matched_count:
                    stat['msg'] = 'Role updated'
                else:
                    authority_result = authority_coll.update_one(
                        {'$or': [{'Authority_ID': user_id}, {'User_ID': user_id}]},
                        {'$set': {'UserRole': new_role}}
                    )
                    if authority_result.matched_count:
                        stat['msg'] = 'Role updated'
                    else:
                        stat['err'] = 'User not found'
        except Exception as e:
            stat['err'] = 'Failed to update role'
            print('Model Error in Update Admin Role: ' + str(e))
        return stat

    def update_admin_status(self, user_id, new_status):
        stat = {'msg': None, 'err': None}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            admin_coll = db['Admin_Users']
            simple_coll = db['Simple_Users']
            authority_coll = db['Authority_Users']

            admin_result = admin_coll.update_one({'$or': [{'User_ID': user_id}, {'Authority_ID': user_id}]}, {'$set': {'Status': new_status}})
            if admin_result.matched_count:
                stat['msg'] = 'Status updated'
            else:
                simple_result = simple_coll.update_one({'$or': [{'User_ID': user_id}, {'Authority_ID': user_id}]}, {'$set': {'Status': new_status}})
                if simple_result.matched_count:
                    stat['msg'] = 'Status updated'
                else:
                    authority_result = authority_coll.update_one(
                        {'$or': [{'Authority_ID': user_id}, {'User_ID': user_id}]},
                        {'$set': {'Status': new_status}}
                    )
                    if authority_result.matched_count:
                        stat['msg'] = 'Status updated'
                    else:
                        stat['err'] = 'User not found'
        except Exception as e:
            stat['err'] = 'Failed to update status'
            print('Model Error in Update Admin Status: ' + str(e))
        return stat

    def delete_admin_user(self, user_id):
        stat = {'msg': None, 'err': None}
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client['UserOperation']
            admin_coll = db['Admin_Users']
            simple_coll = db['Simple_Users']
            authority_coll = db['Authority_Users']

            admin_result = admin_coll.delete_one({'$or': [{'User_ID': user_id}, {'Authority_ID': user_id}]})
            if admin_result.deleted_count:
                stat['msg'] = 'User deleted'
            else:
                simple_result = simple_coll.delete_one({'$or': [{'User_ID': user_id}, {'Authority_ID': user_id}]})
                if simple_result.deleted_count:
                    stat['msg'] = 'User deleted'
                else:
                    authority_result = authority_coll.delete_one(
                        {'$or': [{'Authority_ID': user_id}, {'User_ID': user_id}]}
                    )
                    if authority_result.deleted_count:
                        stat['msg'] = 'User deleted'
                    else:
                        stat['err'] = 'User not found'
        except Exception as e:
            stat['err'] = 'Failed to delete user'
            print('Model Error in Delete Admin User: ' + str(e))
        return stat


# ---------------------------------------------------------------------------
# Notification Operations
# ---------------------------------------------------------------------------
class NotificationOperation:
    DB_NAME = 'CivilOperation'
    LEGACY_DB_NAME = 'UserOperation'
    COLLECTION = 'Notifications'

    def _client(self):
        return MongoClient(settings.MONGO_URI)

    def _coll(self, db_name=None):
        target_db = db_name or self.DB_NAME
        return self._client()[target_db][self.COLLECTION]

    def _read_collections(self):
        names = [self.DB_NAME]
        if self.LEGACY_DB_NAME and self.LEGACY_DB_NAME != self.DB_NAME:
            names.append(self.LEGACY_DB_NAME)
        return [self._coll(name) for name in names]

    def _recipient_candidates(self, username):
        base_value = str(username or '').strip()
        if not base_value:
            return []

        candidates = {base_value}
        client = None
        try:
            client = self._client()
            user_db = client[self.LEGACY_DB_NAME]
            collections = [
                user_db['Simple_Users'],
                user_db['Admin_Users'],
                user_db['Authority_Users'],
            ]
            lookup = {'$or': [{'UserName': base_value}, {'EmailID': base_value}]}
            projection = {'UserName': 1, 'EmailID': 1, 'User_ID': 1, 'Authority_ID': 1}

            for coll in collections:
                row = coll.find_one(lookup, projection)
                if not row:
                    continue
                for key in ['UserName', 'EmailID', 'User_ID', 'Authority_ID']:
                    value = str(row.get(key) or '').strip()
                    if value:
                        candidates.add(value)
        except Exception as e:
            print('Model Error in Notification Recipient Candidates: ' + str(e))
        finally:
            if client:
                client.close()

        return [value for value in candidates if value]

    def _recipient_query(self, username):
        candidate_values = self._recipient_candidates(username)
        if not candidate_values:
            return {'Recipient': '__none__'}

        exact_values = list(dict.fromkeys(candidate_values))
        return {
            '$or': [
                {'Recipient': {'$in': exact_values}},
                {'recipient': {'$in': exact_values}},
                {'RecipientEmail': {'$in': exact_values}},
                {'RecipientAliases': {'$in': exact_values}},
                {'EmailID': {'$in': exact_values}},
                {'UserName': {'$in': exact_values}},
                {'User_ID': {'$in': exact_values}},
                {'Authority_ID': {'$in': exact_values}},
            ]
        }

    def _serialize_notification(self, row):
        rid = row.get('_id')
        created_at = row.get('Created_At') or row.get('created_at') or datetime.now()
        return {
            'id': str(rid) if rid is not None else '',
            'recipient': row.get('Recipient') or row.get('recipient') or '',
            'category': row.get('Category') or row.get('category') or 'System Alert',
            'message': row.get('Message') or row.get('message') or '',
            'related_link': row.get('Related_Link') or row.get('related_link') or '',
            'is_read': bool(row.get('Is_Read') if 'Is_Read' in row else row.get('is_read', False)),
            'created_at': created_at,
            'created_at_iso': created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
        }

    # -----------------------------
    # CREATE NOTIFICATION (Celery Task)
    # -----------------------------
    @staticmethod
    @shared_task
    def create_notification(recipient_username, category, message, related_link=None):
        stat = {}
        try:
            op = NotificationOperation()
            coll = op._coll(op.DB_NAME)
            recipient_values = op._recipient_candidates(recipient_username)
            primary_recipient = recipient_values[0] if recipient_values else recipient_username
            recipient_email = ''
            for value in recipient_values:
                if '@' in str(value):
                    recipient_email = str(value)
                    break

            dic = {}
            dic['Recipient'] = primary_recipient
            dic['recipient'] = primary_recipient
            dic['RecipientAliases'] = recipient_values
            dic['RecipientEmail'] = recipient_email
            dic['Category'] = category          # Status Update | System Alert | Action Required
            dic['Message'] = message
            dic['Related_Link'] = related_link
            dic['Is_Read'] = False
            dic['Created_At'] = datetime.now()
            # Compatibility aliases for consumers expecting snake_case keys
            dic['is_read'] = False
            dic['created_at'] = dic['Created_At']

            coll.create_index([('Recipient', 1), ('Created_At', -1)])
            coll.create_index([('Recipient', 1), ('Is_Read', 1)])
            coll.create_index([('RecipientAliases', 1)])
            coll.insert_one(dic)

            stat['msg'] = 'Notification created successfully'

        except Exception as e:
            stat['err'] = 'Failed to create notification'
            print('Model Error in Create Notification: ' + str(e))

        return stat

    # -----------------------------
    # FETCH USER NOTIFICATIONS
    # -----------------------------
    def fetch_notifications(self, username):
        stat = {
            'msg': None,
            'err': None
        }
        try:
            query = self._recipient_query(username)
            raw_notifications = []
            for coll in self._read_collections():
                raw_notifications.extend(list(coll.find(query).sort('Created_At', -1)))
            notifications = [self._serialize_notification(row) for row in raw_notifications]
            notifications.sort(key=lambda n: n.get('created_at') or datetime.min, reverse=True)

            stat['msg'] = 'Notifications fetched successfully'
            stat['notifications'] = notifications

        except Exception as e:
            stat['err'] = 'Oops! Something went wrong....!'
            print('Model Error in Fetch Notifications: ' + str(e))

        return stat

    # -----------------------------
    # COUNT UNREAD NOTIFICATIONS
    # -----------------------------
    def unread_count(self, username):
        count = 0
        try:
            query = {
                '$and': [
                    self._recipient_query(username),
                    {
                        '$or': [
                            {'Is_Read': False},
                            {'is_read': False},
                            {'Is_Read': {'$exists': False}, 'is_read': {'$exists': False}},
                        ]
                    },
                ]
            }
            for coll in self._read_collections():
                count += coll.count_documents(query)

        except Exception as e:
            print('Model Error in Unread Count: ' + str(e))

        return count

    # -----------------------------
    # MARK ALL AS READ
    # -----------------------------
    def mark_all_as_read(self, username):
        stat = {}
        try:
            modified = 0
            for coll in self._read_collections():
                result = coll.update_many(
                    self._recipient_query(username),
                    {'$set': {'Is_Read': True, 'is_read': True}}
                )
                modified += int(result.modified_count or 0)

            stat['msg'] = 'All notifications marked as read'
            stat['updated'] = modified

        except Exception as e:
            stat['err'] = 'Failed to update notifications'
            print('Model Error in Mark All Read: ' + str(e))

        return stat

    # -----------------------------
    # MARK SINGLE AS READ
    # -----------------------------
    def mark_as_read(self, notification_id, username):
        stat = {}
        try:
            try:
                oid = ObjectId(notification_id)
            except (InvalidId, TypeError, ValueError):
                stat['err'] = 'Invalid notification id.'
                return stat

            matched = 0
            for coll in self._read_collections():
                result = coll.update_one(
                    {
                        '_id': oid,
                        '$or': self._recipient_query(username)['$or'],
                    },
                    {'$set': {'Is_Read': True, 'is_read': True}},
                )
                matched += int(result.matched_count or 0)
                if matched:
                    break

            if matched:
                stat['msg'] = 'Notification marked as read'
            else:
                stat['err'] = 'Notification not found.'

        except Exception as e:
            stat['err'] = 'Failed to update notification'
            print('Model Error in Mark As Read: ' + str(e))

        return stat

    # -----------------------------
    # DELETE SINGLE NOTIFICATION
    # -----------------------------
    def delete_notification(self, notification_id, username):
        stat = {}
        try:
            try:
                oid = ObjectId(notification_id)
            except (InvalidId, TypeError, ValueError):
                stat['err'] = 'Invalid notification id.'
                return stat

            deleted = 0
            for coll in self._read_collections():
                result = coll.delete_one({
                    '_id': oid,
                    '$or': self._recipient_query(username)['$or']
                })
                deleted += int(result.deleted_count or 0)
                if deleted:
                    break

            if deleted:
                stat['msg'] = 'Notification deleted successfully'
            else:
                stat['err'] = 'Notification not found.'

        except Exception as e:
            stat['err'] = 'Failed to delete notification'
            print('Model Error in Delete Notification: ' + str(e))

        return stat

