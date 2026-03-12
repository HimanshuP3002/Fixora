import hashlib
import csv
import json
import os
import glob
import pickle
import re
from copy import deepcopy
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from html import escape
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
import uuid
from pymongo import MongoClient, UpdateOne
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from django.core.paginator import Paginator
from django.core.files.storage import FileSystemStorage
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.conf import settings as django_settings
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from main.models import AIReviewOperation, CivilOperation, NotificationOperation, UserOperation, SystemSettingsDAO


try:
    import phonenumbers
except Exception:
    phonenumbers = None


ADMIN_PANEL_ROLES = {'Super Admin', 'Moderator', 'Editor', 'Admin User'}
AI_REVIEW_ROLES = {'Super Admin', 'Moderator', 'Editor', 'Admin User'}
AI_REVIEW_SYNC_SESSION_KEY = 'ai_review_sync_state_v1'
AI_REVIEW_SYNC_MAX_ROWS = 2000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def has_admin_panel_access(utype):
    return utype in ADMIN_PANEL_ROLES


def has_ai_review_access(utype):
    return utype in AI_REVIEW_ROLES


def has_super_admin_access(utype):
    return utype == 'Super Admin'


def parse_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def parse_international_phone(raw_phone):
    """Return normalized phone details from intl-tel-input E.164 value."""
    raw_phone = (raw_phone or '').strip()
    if not raw_phone:
        return None

    # Preferred path: django-compatible phonenumbers package.
    if phonenumbers:
        try:
            parsed = phonenumbers.parse(raw_phone, None)
            if not phonenumbers.is_valid_number(parsed):
                return None
            return {
                'e164': phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
                'country_code': f"+{parsed.country_code}",
                'national_number': int(parsed.national_number),
            }
        except Exception:
            return None

    # Fallback when package is unavailable.
    digits = re.sub(r'\D', '', raw_phone)
    if not raw_phone.startswith('+') or len(digits) < 8 or len(digits) > 15:
        return None
    if len(digits) <= 6:
        return None
    return {
        'e164': f"+{digits}",
        'country_code': f"+{digits[:-10] if len(digits) > 10 else digits[:2]}",
        'national_number': int(digits[-10:]) if len(digits) >= 10 else int(digits),
    }


def get_india_festival_theme(today=None, settings_data=None):
    """
    Return UI festival theme using month/day matching so it works every year.
    For lunar/movable festivals, update the table yearly with the new dates.
    """
    today = today or timezone.localdate()
    settings_data = settings_data or {}
    festival_settings = (settings_data.get('festival') or {})

    eclipse_type = (festival_settings.get('eclipse_type') or 'Chandra Grahan').strip()
    eclipse_theme = {
        'name': eclipse_type,
        'accent': '#0f172a' if eclipse_type == 'Chandra Grahan' else '#111827',
        'bg_soft': '#0b1220' if eclipse_type == 'Chandra Grahan' else '#0b1020',
        'glow': 'rgba(56, 189, 248, 0.18)' if eclipse_type == 'Chandra Grahan' else 'rgba(244, 114, 182, 0.18)',
        'symbol': 'ECLIPSE',
        'scene': 'moon' if eclipse_type == 'Chandra Grahan' else 'sun',
    }

    festival_by_month_day = {
        (1, 14): {'name': 'Makar Sankranti', 'accent': '#f59e0b', 'bg_soft': '#fffbeb', 'glow': 'rgba(245,158,11,0.32)', 'symbol': 'KITE', 'scene': 'kite'},
        (1, 23): {'name': 'Vasant Panchami', 'accent': '#facc15', 'bg_soft': '#fefce8', 'glow': 'rgba(250,204,21,0.30)', 'symbol': 'BLOOM', 'scene': 'flower'},
        (1, 26): {'name': 'Republic Day', 'accent': '#16a34a', 'bg_soft': '#ecfdf3', 'glow': 'rgba(22,163,74,0.26)', 'symbol': 'FLAG', 'scene': 'flag'},
        (2, 15): {'name': 'Maha Shivaratri', 'accent': '#4f46e5', 'bg_soft': '#eef2ff', 'glow': 'rgba(79,70,229,0.30)', 'symbol': 'TRIDENT', 'scene': 'trident'},
        (2, 18): {'name': 'Losar', 'accent': '#0ea5e9', 'bg_soft': '#f0f9ff', 'glow': 'rgba(14,165,233,0.30)', 'symbol': 'PRAYER', 'scene': 'moon'},
        (3, 4): {'name': 'Holi', 'accent': '#db2777', 'bg_soft': '#fff1f2', 'glow': 'rgba(219,39,119,0.30)', 'symbol': 'COLOR', 'scene': 'color'},
        (3, 21): {'name': 'Eid-ul-Fitr', 'accent': '#059669', 'bg_soft': '#ecfdf5', 'glow': 'rgba(5,150,105,0.30)', 'symbol': 'MOON', 'scene': 'moon'},
        (3, 22): {'name': 'Ugadi / Gudi Padwa / Chaitra Navratri (Start)', 'accent': '#f97316', 'bg_soft': '#fff7ed', 'glow': 'rgba(249,115,22,0.30)', 'symbol': 'LEAF', 'scene': 'leaf'},
        (3, 30): {'name': 'Ram Navami', 'accent': '#ea580c', 'bg_soft': '#fff7ed', 'glow': 'rgba(234,88,12,0.30)', 'symbol': 'ARROW', 'scene': 'arrow'},
        (4, 2): {'name': 'Mahavir Jayanti', 'accent': '#84cc16', 'bg_soft': '#f7fee7', 'glow': 'rgba(132,204,22,0.30)', 'symbol': 'WHEEL', 'scene': 'wheel'},
        (4, 3): {'name': 'Good Friday', 'accent': '#64748b', 'bg_soft': '#f8fafc', 'glow': 'rgba(100,116,139,0.24)', 'symbol': 'CROSS', 'scene': 'cross'},
        (4, 5): {'name': 'Easter', 'accent': '#0ea5e9', 'bg_soft': '#f0f9ff', 'glow': 'rgba(14,165,233,0.28)', 'symbol': 'EASTER', 'scene': 'star'},
        (4, 14): {'name': 'Baisakhi / Rongali Bihu', 'accent': '#eab308', 'bg_soft': '#fefce8', 'glow': 'rgba(234,179,8,0.30)', 'symbol': 'HARVEST', 'scene': 'leaf'},
        (5, 1): {'name': 'Buddha Purnima', 'accent': '#0284c7', 'bg_soft': '#f0f9ff', 'glow': 'rgba(2,132,199,0.30)', 'symbol': 'LOTUS', 'scene': 'lotus'},
        (5, 5): {'name': 'Thrissur Pooram', 'accent': '#b45309', 'bg_soft': '#fffbeb', 'glow': 'rgba(180,83,9,0.30)', 'symbol': 'DRUM', 'scene': 'drum'},
        (6, 26): {'name': 'Rath Yatra', 'accent': '#b91c1c', 'bg_soft': '#fef2f2', 'glow': 'rgba(185,28,28,0.30)', 'symbol': 'CHARIOT', 'scene': 'wheel'},
        (7, 4): {'name': 'Hemis Festival', 'accent': '#7c3aed', 'bg_soft': '#f5f3ff', 'glow': 'rgba(124,58,237,0.30)', 'symbol': 'MASK', 'scene': 'drum'},
        (7, 5): {'name': 'Dree Festival', 'accent': '#0891b2', 'bg_soft': '#ecfeff', 'glow': 'rgba(8,145,178,0.30)', 'symbol': 'GRAIN', 'scene': 'leaf'},
        (8, 15): {'name': 'Independence Day', 'accent': '#15803d', 'bg_soft': '#ecfdf5', 'glow': 'rgba(21,128,61,0.26)', 'symbol': 'FLAG', 'scene': 'flag'},
        (8, 30): {'name': 'Raksha Bandhan', 'accent': '#c026d3', 'bg_soft': '#fdf4ff', 'glow': 'rgba(192,38,211,0.28)', 'symbol': 'RAKHI', 'scene': 'wheel'},
        (9, 5): {'name': 'Janmashtami', 'accent': '#2563eb', 'bg_soft': '#eff6ff', 'glow': 'rgba(37,99,235,0.30)', 'symbol': 'FLUTE', 'scene': 'flute'},
        (9, 6): {'name': 'Onam (Thiruvonam)', 'accent': '#f59e0b', 'bg_soft': '#fffbeb', 'glow': 'rgba(245,158,11,0.30)', 'symbol': 'FLOWER', 'scene': 'flower'},
        (9, 14): {'name': 'Ganesh Chaturthi', 'accent': '#f97316', 'bg_soft': '#fff7ed', 'glow': 'rgba(249,115,22,0.30)', 'symbol': 'GANESHA', 'scene': 'lotus'},
        (10, 18): {'name': 'Sharad Navratri (Start)', 'accent': '#dc2626', 'bg_soft': '#fef2f2', 'glow': 'rgba(220,38,38,0.30)', 'symbol': 'GARBA', 'scene': 'color'},
        (10, 26): {'name': 'Durga Puja (Ashtami)', 'accent': '#be123c', 'bg_soft': '#fff1f2', 'glow': 'rgba(190,18,60,0.30)', 'symbol': 'DURGA', 'scene': 'trident'},
        (10, 27): {'name': 'Dussehra (Vijayadashami)', 'accent': '#ea580c', 'bg_soft': '#fff7ed', 'glow': 'rgba(234,88,12,0.30)', 'symbol': 'VICTORY', 'scene': 'arrow'},
        (11, 9): {'name': 'Diwali', 'accent': '#d97706', 'bg_soft': '#fff7ed', 'glow': 'rgba(217,119,6,0.34)', 'symbol': 'DIYA', 'scene': 'diya'},
        (11, 10): {'name': 'Govardhan Puja / Chhath Puja', 'accent': '#0ea5e9', 'bg_soft': '#f0f9ff', 'glow': 'rgba(14,165,233,0.30)', 'symbol': 'SUN', 'scene': 'sun'},
        (11, 24): {'name': 'Gurpurab (Guru Nanak Jayanti)', 'accent': '#16a34a', 'bg_soft': '#f0fdf4', 'glow': 'rgba(22,163,74,0.30)', 'symbol': 'SEVA', 'scene': 'moon'},
        (12, 1): {'name': 'Hornbill Festival (Start)', 'accent': '#7c2d12', 'bg_soft': '#fff7ed', 'glow': 'rgba(124,45,18,0.30)', 'symbol': 'HORNBILL', 'scene': 'leaf'},
        (12, 25): {'name': 'Christmas', 'accent': '#dc2626', 'bg_soft': '#fef2f2', 'glow': 'rgba(220,38,38,0.28)', 'symbol': 'STAR', 'scene': 'star'},
    }
    festival_by_name = {value['name']: value for value in festival_by_month_day.values()}
    festival_by_name[eclipse_theme['name']] = eclipse_theme
    festival_by_name['Eclipse Night'] = eclipse_theme

    def theme_payload(theme):
        return {
            'name': theme['name'],
            'banner': f"{theme['name']} Theme Active",
            'accent': theme['accent'],
            'bg_soft': theme['bg_soft'],
            'glow': theme['glow'],
            'animation_enabled': True,
            'animation_symbol': theme['symbol'],
            'animation_scene': theme.get('scene', 'idle'),
        }

    auto_mode = festival_settings.get('auto_mode', True)
    if isinstance(auto_mode, str):
        auto_mode = auto_mode.strip().lower() not in {'0', 'false', 'off', 'no'}
    else:
        auto_mode = bool(auto_mode)

    override_date = (festival_settings.get('override_date') or '').strip()
    selected_festival = (festival_settings.get('selected_festival') or '').strip()
    if selected_festival and selected_festival in festival_by_name:
        selected_theme = festival_by_name[selected_festival]
        if not auto_mode:
            # Manual mode: selected festival is controlled from admin settings.
            if not override_date or today.isoformat() == override_date:
                return theme_payload(selected_theme)
        elif override_date and today.isoformat() == override_date:
            # Auto mode + custom date override for selected festival.
            return theme_payload(selected_theme)

    eclipse_date = (festival_settings.get('eclipse_date') or '').strip()
    eclipse_start = (festival_settings.get('eclipse_start') or '').strip()
    eclipse_end = (festival_settings.get('eclipse_end') or '').strip()
    now = timezone.localtime()

    def within_range(start_str, end_str):
        try:
            start_dt = timezone.make_aware(datetime.fromisoformat(start_str))
            end_dt = timezone.make_aware(datetime.fromisoformat(end_str))
        except Exception:
            return False
        return start_dt <= now <= end_dt

    if eclipse_start and eclipse_end and within_range(eclipse_start, eclipse_end):
        return theme_payload(eclipse_theme)

    if eclipse_date and today.isoformat() == eclipse_date:
        return theme_payload(eclipse_theme)

    theme = festival_by_month_day.get((today.month, today.day))
    if theme:
        return theme_payload(theme)

    return {
        'name': 'Default',
        'banner': '',
        'accent': '#334155',
        'bg_soft': '#f8fafc',
        'glow': 'rgba(51, 65, 85, 0.12)',
        'animation_enabled': False,
        'animation_symbol': '',
        'animation_scene': 'idle',
    }


def themed_render(request, template_name, context=None):
    ctx = dict(context or {})
    settings_data = SystemSettingsDAO().get_current_settings(cache_backend=cache).get('settings', {})
    ctx.setdefault('system_settings', settings_data)
    ctx.setdefault('festival_theme', get_india_festival_theme(settings_data=settings_data))
    if settings_data.get('general', {}).get('maintenance_mode') and not request.path.startswith('/admin'):
        return render(request, 'main/maintenance.html', ctx, status=503)
    ctx.setdefault('flash_msg', request.GET.get('msg', ''))
    ctx.setdefault('flash_err', request.GET.get('err', ''))
    try:
        if request.session.get('user'):
            unread = NotificationOperation().unread_count(request.session.get('user'))
            request.session['unread_notifications'] = unread
            ctx.setdefault('unread_count', unread)
    except Exception:
        pass
    return render(request, template_name, ctx)


def get_latest_training_metadata():
    artifact_dir = os.path.join(django_settings.BASE_DIR, 'static', 'assets', 'ml_artifacts')
    if not os.path.exists(artifact_dir):
        return None
    candidates = glob.glob(os.path.join(artifact_dir, 'issue_*_model_*.json'))
    if not candidates:
        return None
    latest_path = max(candidates, key=os.path.getmtime)
    try:
        with open(latest_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        metadata['metadata_path'] = latest_path
        return metadata
    except Exception:
        return None


def sync_ai_review_predictions_from_latest_model(settings_data=None):
    """
    Build or refresh AI review queue records from Issue data using latest trained model.
    This keeps AI Review table populated even when records were never inserted manually.
    """
    try:
        settings_data = settings_data or SystemSettingsDAO().get_current_settings(cache_backend=cache).get('settings', {})
        ai_settings = (settings_data.get('ai_system') or {})
        if not ai_settings.get('enable_ai_training_queue', True):
            return {'synced': 0, 'skipped': 'ai_queue_disabled'}
        try:
            sync_max_rows = int(ai_settings.get('review_sync_max_rows', AI_REVIEW_SYNC_MAX_ROWS))
        except Exception:
            sync_max_rows = AI_REVIEW_SYNC_MAX_ROWS
        sync_max_rows = max(100, sync_max_rows)

        metadata = get_latest_training_metadata()
        if not metadata:
            return {'synced': 0, 'skipped': 'no_trained_model'}

        metadata_path = (metadata.get('metadata_path') or '').strip()
        if not metadata_path.endswith('.json'):
            return {'synced': 0, 'skipped': 'invalid_metadata_path'}
        model_path = metadata_path[:-5] + '.pkl'
        if not os.path.exists(model_path):
            return {'synced': 0, 'skipped': 'model_artifact_not_found'}

        with open(model_path, 'rb') as f:
            model = pickle.load(f)

        target = (metadata.get('target') or 'Category').strip()
        client = MongoClient(django_settings.MONGO_URI)
        db = client['CivilOperation']
        issue_coll = db['Issue']
        review_coll = db['AIReviewRecords']

        issue_projection = {
            '_id': 0,
            'OriginalIssueID': 1,
            'IssueID': 1,
            'issue_id': 1,
            'Title': 1,
            'Description': 1,
            'Category': 1,
            'Urgency': 1,
            'Status': 1,
            'Location': 1,
            'Department': 1,
            'Image': 1,
            'ReportedBy': 1,
            'IssueDate': 1,
        }
        issue_rows = list(
            issue_coll.find({}, issue_projection).sort('IssueDate', -1).limit(sync_max_rows)
        )
        if not issue_rows:
            return {'synced': 0, 'skipped': 'no_issue_rows'}

        rows_for_prediction = []
        texts = []
        for row in issue_rows:
            text = " ".join([
                (row.get('Title') or '').strip(),
                (row.get('Description') or '').strip(),
                (row.get('Location') or '').strip(),
                (row.get('Department') or '').strip(),
            ]).strip()
            if not text:
                continue
            rows_for_prediction.append(row)
            texts.append(text)

        if not texts:
            return {'synced': 0, 'skipped': 'no_prediction_text'}

        predictions = model.predict(texts)
        confidences = [0.5] * len(texts)
        if hasattr(model, 'predict_proba'):
            try:
                prob_rows = model.predict_proba(texts)
                for idx, prob_row in enumerate(prob_rows):
                    try:
                        confidences[idx] = float(max(prob_row))
                    except Exception:
                        confidences[idx] = 0.5
            except Exception:
                pass

        source_issue_ids = []
        for row in rows_for_prediction:
            candidate_issue_id = (
                row.get('OriginalIssueID')
                or row.get('IssueID')
                or row.get('issue_id')
                or ''
            )
            candidate_issue_id = str(candidate_issue_id).strip()
            if candidate_issue_id:
                source_issue_ids.append(candidate_issue_id)

        existing_status_by_issue = {}
        if source_issue_ids:
            for existing_row in review_coll.find(
                {'SourceIssueID': {'$in': source_issue_ids}},
                {'_id': 0, 'SourceIssueID': 1, 'Status': 1},
            ):
                key = str(existing_row.get('SourceIssueID') or '').strip()
                if key:
                    existing_status_by_issue[key] = (existing_row.get('Status') or '').strip().lower()

        synced = 0
        bulk_ops = []
        model_tag = os.path.basename(model_path)
        for idx, row in enumerate(rows_for_prediction):
            issue_id = (
                row.get('OriginalIssueID')
                or row.get('IssueID')
                or row.get('issue_id')
                or ''
            )
            issue_id = str(issue_id).strip()
            if not issue_id:
                continue

            predicted_raw = str(predictions[idx] if idx < len(predictions) else '')
            issue_category = (row.get('Category') or 'Uncategorized').strip()
            issue_urgency = (row.get('Urgency') or 'Medium').strip()

            if target == 'Category':
                predicted_label = predicted_raw or issue_category
                predicted_severity = issue_urgency
            elif target == 'Urgency':
                predicted_label = issue_category
                predicted_severity = predicted_raw or issue_urgency
            else:
                predicted_label = issue_category
                predicted_severity = issue_urgency

            reasoning = (
                f"Predicted using latest issue model ({target}) from {model_tag}. "
                f"Source fields: Title, Description, Location, Department."
            )
            created_at = row.get('IssueDate') if isinstance(row.get('IssueDate'), datetime) else datetime.now()
            update_doc = {
                'Image': row.get('Image') or '',
                'PredictedLabel': predicted_label,
                'PredictedSeverity': predicted_severity,
                'Confidence': float(confidences[idx]),
                'UploadedBy': row.get('ReportedBy') or 'System',
                'Status': 'pending',
                'AIReasoning': reasoning,
                'SourceIssueID': issue_id,
                'CreatedAt': created_at,
                'ModelTarget': target,
                'ModelTag': model_tag,
            }

            existing_status = existing_status_by_issue.get(issue_id)
            if existing_status in {'reviewed', 'rejected'}:
                continue

            bulk_ops.append(
                UpdateOne(
                    {'SourceIssueID': issue_id},
                    {
                        '$set': update_doc,
                        '$setOnInsert': {'RecordID': f"AIR-{issue_id}"},
                    },
                    upsert=True,
                )
            )
            synced += 1

        if bulk_ops:
            review_coll.bulk_write(bulk_ops, ordered=False)

        return {'synced': synced, 'target': target, 'sync_max_rows': sync_max_rows}
    except Exception as e:
        print('View Error in AI Review Queue Sync:', str(e))
        return {'synced': 0, 'err': str(e)}


def sync_ai_review_once_per_session(request, settings_data=None):
    """Run expensive AI review sync only once in the active user session."""
    existing_state = request.session.get(AI_REVIEW_SYNC_SESSION_KEY)
    if isinstance(existing_state, dict) and existing_state.get('done'):
        return existing_state.get('result') or {'synced': 0, 'skipped': 'session_cached'}

    result = sync_ai_review_predictions_from_latest_model(settings_data=settings_data)
    request.session[AI_REVIEW_SYNC_SESSION_KEY] = {
        'done': True,
        'synced_at': timezone.now().isoformat(),
        'result': result,
    }
    request.session.modified = True
    return result


def predict_future_hotspots(username, utype, top_n=5, lookback_days=30, max_rows=5000):
    """
    Heuristic hotspot predictor for dashboard ticker.
    Scores locations using recent volume, trend, urgency, and unresolved ratio.
    """
    hotspots = []
    try:
        client = MongoClient(django_settings.MONGO_URI)
        db = client['CivilOperation']
        coll = db['Issue']

        now = datetime.now()
        since = now - timedelta(days=max(lookback_days, 7))
        recent_cutoff = now - timedelta(days=7)
        prev_cutoff = now - timedelta(days=14)

        query = {'IssueDate': {'$gte': since}}
        if utype not in ADMIN_PANEL_ROLES:
            username_text = str(username or '').strip()
            username_pattern = {'$regex': f'^{re.escape(username_text)}$', '$options': 'i'}
            query['$or'] = [
                {'ReportedBy': username_pattern},
                {'reported_by': username_pattern},
                {'reporter': username_pattern},
                {'UserName': username_pattern},
                {'EmailID': username_pattern},
            ]

        projection = {
            '_id': 0,
            'Location': 1,
            'lat': 1,
            'lng': 1,
            'Urgency': 1,
            'Status': 1,
            'IssueDate': 1,
        }
        rows = list(coll.find(query, projection).sort('IssueDate', -1).limit(max_rows))
        if not rows:
            return hotspots

        grouped = defaultdict(lambda: {
            'total': 0,
            'recent7': 0,
            'prev7': 0,
            'high_urgency': 0,
            'unresolved': 0,
            'lat': None,
            'lng': None,
        })

        for row in rows:
            location = str(row.get('Location') or '').strip()
            if not location:
                continue

            bucket = grouped[location]
            bucket['total'] += 1
            if bucket['lat'] is None and row.get('lat') is not None:
                bucket['lat'] = row.get('lat')
            if bucket['lng'] is None and row.get('lng') is not None:
                bucket['lng'] = row.get('lng')

            issue_date = row.get('IssueDate')
            if isinstance(issue_date, datetime):
                if issue_date >= recent_cutoff:
                    bucket['recent7'] += 1
                elif issue_date >= prev_cutoff:
                    bucket['prev7'] += 1

            urgency = str(row.get('Urgency') or '').strip().lower()
            if urgency in {'high', 'critical'}:
                bucket['high_urgency'] += 1

            status = str(row.get('Status') or '').strip().lower()
            if status != 'resolved':
                bucket['unresolved'] += 1

        scored = []
        for location, data in grouped.items():
            growth = max(data['recent7'] - data['prev7'], 0)
            score = (
                (1.0 * data['total'])
                + (2.0 * data['high_urgency'])
                + (1.5 * data['unresolved'])
                + (2.0 * growth)
            )
            if score >= 20:
                risk_level = 'high'
            elif score >= 10:
                risk_level = 'medium'
            else:
                risk_level = 'low'
            trend = 'rising' if growth > 0 else 'stable'
            scored.append({
                'location': location,
                'score': round(score, 1),
                'cases': data['total'],
                'trend': trend,
                'risk_level': risk_level,
                'lat': data['lat'],
                'lng': data['lng'],
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        hotspots = scored[:max(top_n, 1)]
    except Exception as e:
        print('View Error in Predict Future Hotspots:', str(e))

    return hotspots

# ---------------------------------------------------------------------------
# Dashboard / Landing
# ---------------------------------------------------------------------------
@csrf_exempt
def index(request):

    if 'user' in request.session:
        obj = CivilOperation()
        stat = obj.count()
        dic = stat

        name = request.session['user']

        v = UserOperation()
        utype = request.session.get('utype') or v.checkType(name)
        request.session['utype'] = utype
        request.session['user_email'] = v.get_user_email(name) or name

        # ✅ ADD: fetch latest issues via model
        issue_data = obj.fetch_all_issues(
            username=name,
            utype=utype
        )
        dic['latest_issues'] = issue_data.get('issues', [])
        dic['future_hotspots'] = predict_future_hotspots(username=name, utype=utype)

        return themed_render(request, 'main/index.html', dic)

    else:
        return themed_render(request, 'main/login.html', {'err': 'Please Login First...!'})


# ---------------------------------------------------------------------------
# Auth / User Registration
# ---------------------------------------------------------------------------
def register(request):
    dic = {}
    try:
        if request.method == 'POST':
            fname = request.POST.get('name')
            user = request.POST.get('user')
            email = request.POST.get('email')                   
            pwd = request.POST.get('pass')
            cpwd = request.POST.get('cpass')
            terms = request.POST.get('terms')

            if not terms:
                dic['err'] = 'You must agree to the terms and conditions.'
                return themed_render(request, 'main/register.html', dic)
            if pwd != cpwd:
                dic['err'] = 'Passwords do not match.'
                return themed_render(request, 'main/register.html', dic)
            
            obj = UserOperation()
            stat = obj.register_user(fname, user, email, pwd)
            dic = stat
    except Exception as e:
        dic['err'] = 'Oops! Something went wrong....!'
        print('View Error in Register: ' + str(e))

    return themed_render(request, 'main/register.html', dic)

@csrf_exempt
def admin_registration(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        return redirect('main:index')

    dic = {}
    obj = UserOperation()

    if request.method == 'GET':
        dic['AdminID'] = obj.get_preview_admin_id()

    try:
        if request.method == 'POST':
            dic['AdminID'] = obj.get_preview_admin_id()
            full_name = request.POST.get('admin_full_name')
            username = request.POST.get('admin_username')
            email = request.POST.get('admin_email')
            password = request.POST.get('admin_password')
            confirm_password = request.POST.get('admin_confirm_password')
            role = request.POST.get('admin_role')
            security_token = request.POST.get('security_token')
            profile_picture = request.FILES.get('profile_picture')

            if password != confirm_password:
                dic['err'] = 'Passwords do not match.'
                return themed_render(request, 'main/admin_registration.html', dic)

            stat = obj.register_admin_user(
                fname=full_name,
                user=username,
                email=email,
                pwd=password,
                role=role,
                security_token=security_token,
                avatar=profile_picture
            )
            dic = stat

            if 'AdminID' not in dic:
                dic['AdminID'] = obj.get_preview_admin_id()
    except Exception as e:
        dic['err'] = 'Oops! Something went wrong....!'
        if 'AdminID' not in dic:
            dic['AdminID'] = obj.get_preview_admin_id()
        print('View Error in Admin Register: ' + str(e))

    return themed_render(request, 'main/admin_registration.html', dic)


@csrf_exempt
def add_user(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        return redirect('main:index')

    obj = UserOperation()
    dic = {
        'user_type': 'simple',
        'AdminID': obj.get_preview_admin_id(),
        'GeneratedEmployeeID': obj.get_preview_employee_id(),
    }

    try:
        if request.method == 'POST':
            user_type = (request.POST.get('user_type') or 'simple').strip().lower()
            full_name = (request.POST.get('full_name') or '').strip()
            username = (request.POST.get('username') or '').strip()
            email = (request.POST.get('email') or '').strip().lower()
            password = request.POST.get('password') or ''
            confirm_password = request.POST.get('confirm_password') or ''

            dic['user_type'] = user_type
            dic['AdminID'] = obj.get_preview_admin_id()
            dic['GeneratedEmployeeID'] = obj.get_preview_employee_id()

            if not all([full_name, username, email, password, confirm_password]):
                dic['err'] = 'Please fill all required fields.'
                return themed_render(request, 'main/add_user.html', dic)

            if password != confirm_password:
                dic['err'] = 'Passwords do not match.'
                return themed_render(request, 'main/add_user.html', dic)

            if len(password) < 8:
                dic['err'] = 'Password must be at least 8 characters.'
                return themed_render(request, 'main/add_user.html', dic)

            if user_type == 'simple':
                stat = obj.register_user(full_name, username, email, password)
                dic.update(stat)

            elif user_type == 'admin':
                admin_role_selected = (request.POST.get('admin_role') or '').strip()
                profile_picture = request.FILES.get('profile_picture')

                if admin_role_selected not in ['Super Admin', 'Moderator', 'Editor']:
                    dic['err'] = 'Please choose a valid admin role.'
                    return themed_render(request, 'main/add_user.html', dic)

                stat = obj.register_admin_user(
                    fname=full_name,
                    user=username,
                    email=email,
                    pwd=password,
                    role=admin_role_selected,
                    security_token='FIXORA-ADMIN-2026',
                    avatar=profile_picture
                )
                dic.update(stat)

            elif user_type == 'authority':
                department_name = (request.POST.get('department_name') or '').strip()
                employee_id = (request.POST.get('employee_id') or '').strip()
                phone_number_full = (request.POST.get('phone_number_full') or '').strip()
                authority_role = (request.POST.get('authority_role') or '').strip()
                verification_document = request.FILES.get('verification_document')

                if not all([department_name, employee_id, phone_number_full, authority_role]):
                    dic['err'] = 'Please fill authority details.'
                    return themed_render(request, 'main/add_user.html', dic)

                if authority_role not in ['Officer', 'Supervisor']:
                    dic['err'] = 'Please choose a valid authority role.'
                    return themed_render(request, 'main/add_user.html', dic)

                phone_data = parse_international_phone(phone_number_full)
                if not phone_data:
                    dic['err'] = 'Please enter a valid international phone number.'
                    return themed_render(request, 'main/add_user.html', dic)

                password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
                stat = obj.register_authority_user(
                    full_name=full_name,
                    department_name=department_name,
                    official_email=email,
                    employee_id=employee_id,
                    phone_country_code=phone_data['country_code'],
                    phone_number=phone_data['national_number'],
                    phone_number_e164=phone_data['e164'],
                    role=authority_role,
                    password_hash=password_hash,
                    verification_document=verification_document
                )
                dic.update(stat)

            else:
                dic['err'] = 'Invalid user type selected.'

            if dic.get('msg'):
                dic['user_type'] = 'simple'
                dic['AdminID'] = obj.get_preview_admin_id()
                dic['GeneratedEmployeeID'] = obj.get_preview_employee_id()

    except Exception as e:
        dic['err'] = 'Oops! Something went wrong....!'
        print('View Error in Add User: ' + str(e))

    return themed_render(request, 'main/add_user.html', dic)

@csrf_exempt
def authority_registration(request):
    dic = {}
    obj = UserOperation()

    try:
        if request.method == 'POST':
            full_name = (request.POST.get('full_name') or '').strip()
            department_name = (request.POST.get('department_name') or '').strip()
            official_email = (request.POST.get('official_email') or '').strip().lower()
            employee_id = (request.POST.get('employee_id') or '').strip()
            phone_number_full = (request.POST.get('phone_number_full') or '').strip()
            role = (request.POST.get('role') or '').strip()
            password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')
            terms = request.POST.get('terms')
            verification_document = request.FILES.get('verification_document')

            if not all([full_name, department_name, official_email, employee_id, phone_number_full, role, password, confirm_password]):
                dic['err'] = 'All fields are required.'
                return themed_render(request, 'main/authority_registration.html', dic)

            phone_data = parse_international_phone(phone_number_full)
            if not phone_data:
                dic['err'] = 'Please enter a valid international phone number.'
                return themed_render(request, 'main/authority_registration.html', dic)

            if role not in ['Officer', 'Supervisor']:
                dic['err'] = 'Please select a valid role.'
                return themed_render(request, 'main/authority_registration.html', dic)

            if not terms:
                dic['err'] = 'You must agree before submitting your request.'
                return themed_render(request, 'main/authority_registration.html', dic)

            if password != confirm_password:
                dic['err'] = 'Passwords do not match.'
                return themed_render(request, 'main/authority_registration.html', dic)

            if len(password) < 8:
                dic['err'] = 'Password must be at least 8 characters long.'
                return themed_render(request, 'main/authority_registration.html', dic)

            if not verification_document:
                dic['err'] = 'Verification document is required.'
                return themed_render(request, 'main/authority_registration.html', dic)

            password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()

            stat = obj.register_authority_user(
                full_name=full_name,
                department_name=department_name,
                official_email=official_email,
                employee_id=employee_id,
                phone_country_code=phone_data['country_code'],
                phone_number=phone_data['national_number'],
                phone_number_e164=phone_data['e164'],
                role=role,
                password_hash=password_hash,
                verification_document=verification_document
            )
            dic.update(stat)
    except Exception as e:
        dic['err'] = 'Oops! Something went wrong....!'
        print('View Error in Authority Register: ' + str(e))

    return themed_render(request, 'main/authority_registration.html', dic)

def login(request):
    dic = {
        'msg' : None,
        'err' : None
    }
    providers = django_settings.SOCIALACCOUNT_PROVIDERS or {}
    google_app = (providers.get('google') or {}).get('APP', {}) or {}
    facebook_app = (providers.get('facebook') or {}).get('APP', {}) or {}
    dic['google_enabled'] = bool(google_app.get('client_id') and google_app.get('secret'))
    dic['facebook_enabled'] = bool(facebook_app.get('client_id') and facebook_app.get('secret'))

    if 'user' in request.session:
        request.session.pop('user', None)
        request.session.pop('new', None)

    if request.method == 'POST':
        user = request.POST.get('user')
        pwd = request.POST.get('pass')

        obj = UserOperation()
        stat = obj.login_user(user, pwd)
        dic.update(stat)

        if dic['msg']:
            dic['msg'] = 'Login Successful'
            print(dic)
            request.session['user'] = user
            request.session['fname'] = dic['fname']
            request.session['utype'] = dic.get('utype') or UserOperation().checkType(user)
            request.session['user_email'] = UserOperation().get_user_email(user) or user
            request.session['new'] = 1
            print("Session Set...!")
            return redirect('main:index')
        else:
            dic['err'] = "Invalid Credentials. Please try again."

    return themed_render(request, 'main/login.html', dic)


@login_required
def social_auth_sync(request):
    email = (request.user.email or '').strip().lower()
    username = (request.user.username or '').strip()
    full_name = (request.user.get_full_name() or username or email).strip()

    if not email:
        return redirect('main:login')

    user_ops = UserOperation()
    social_user = user_ops.ensure_social_user(full_name=full_name, username=username, email=email)

    session_identity = social_user.get('login_key') or username or email
    request.session['user'] = session_identity
    request.session['fname'] = social_user.get('full_name') or full_name or session_identity
    request.session['utype'] = social_user.get('user_role') or user_ops.checkType(session_identity)
    request.session['user_email'] = social_user.get('email') or email
    request.session['new'] = 1

    return redirect('main:index')
# ---------------------------------------------------------------------------
# Issue Reporting / Citizen Views
# ---------------------------------------------------------------------------
@csrf_exempt
def report_issue(request):
    dic = {}

    if 'user' not in request.session:
        return redirect('main:login')

    obj = CivilOperation()

    # PREVIEW ID
    if request.method == "GET":
        dic['IssueID'] = obj.get_preview_issue_id()

    if request.method == "POST":
        cat = request.POST.get('cat')
        ttl = request.POST.get('ttl')
        desc = request.POST.get('desc')
        loc = request.POST.get('loc')
        user = request.session['user']
        img = request.FILES.get('img')
        cont_raw = request.POST.get('cont')
        phone_data = parse_international_phone(cont_raw)
        cont = phone_data['national_number'] if phone_data else None
        cont_e164 = phone_data['e164'] if phone_data else ''
        lnd = request.POST.get('lnd')
        urg = request.POST.get('urg')

        stat = obj.register_issue(
            cat,
            ttl,
            loc,
            desc,
            img,
            user,
            cont,
            lnd,
            urg,
            contact_e164=cont_e164,
        )

        dic.update(stat)

        # 🔑 IMPORTANT: keep preview ID visible if error
        if 'IssueID' not in dic:
            dic['IssueID'] = obj.get_preview_issue_id()

    return themed_render(request, 'main/report_issue.html', dic)

@csrf_exempt
def my_issues(request):
    if 'user' in request.session:
        current_user = request.session['user']
        
        # Create object and call the function with the username
        obj = CivilOperation()
        user_issues = obj.fetch_issues(current_user)
        
        return themed_render(request, 'main/my_issues.html', {'issues': user_issues})
    else:
        return redirect('main:login')

@csrf_exempt
def issue_detail(request, issue_id):
    # 1. Security Check
    if 'user' not in request.session:
        return redirect('main:login')

    # 2. Fetch Data
    obj = CivilOperation()
    
    # Pass the string ID (e.g., "ISSUE-002") directly to the model
    issue_data = obj.get_issue_by_id(issue_id) 
    
    # 3. Check if issue exists
    if issue_data:
        # Since we are using IssueID, we don't need to convert _id to string
        # We can pass the data directly to the template
        return themed_render(request, 'main/issue_detail.html', {'issue': issue_data})
    else:
        # Redirect if ID is invalid or not found
        return redirect('main:my_issues')


@csrf_exempt
def issue_overview(request):
    if 'user' not in request.session:
        return redirect('main:login')

    return themed_render(request, 'main/issue_overview.html')

@csrf_exempt
def map_view(request):
    if 'user' not in request.session:
        return redirect('main:login')

    obj = CivilOperation()

    # Lightweight fetch for initial map load
    result = obj.fetch_map_issues()

    issues = []
    if result and result.get('issues'):
        issues = result['issues']

    return themed_render(
        request,
        'main/map_view.html',
        {
            'issues': issues
        }
    )

@csrf_exempt
def profile(request):
    if 'user' not in request.session:
        return redirect('main:login')
    username = request.session['user']

    user_op = UserOperation()

    page_msg = None
    page_err = None
    if request.method == 'POST':
        full_name = (request.POST.get('full_name') or '').strip()
        update_result = user_op.update_user_full_name(username, full_name)
        if update_result.get('msg'):
            page_msg = update_result.get('msg')
        else:
            page_err = update_result.get('err') or 'Unable to update profile.'

    stat = user_op.fetch_user_details(username)

    def role_links(role_name):
        mapping = {
            'Simple User': [
                {'label': 'Report Issue', 'url': reverse('main:report_issues')},
                {'label': 'My Issues', 'url': reverse('main:my_issues')},
                {'label': 'Map View', 'url': reverse('main:map_view')},
                {'label': 'Notifications', 'url': reverse('main:notification')},
            ],
            'Authority': [
                {'label': 'Live Issue Feed', 'url': reverse('main:fetch_issue_admin')},
                {'label': 'Assigned Issues', 'url': reverse('main:issue_management')},
                {'label': 'Priority Queue', 'url': reverse('main:priority_queue')},
                {'label': 'Work Orders', 'url': reverse('main:work_orders')},
                {'label': 'Notifications', 'url': reverse('main:notification')},
            ],
            'Editor': [
                {'label': 'Assigned Issues', 'url': reverse('main:fetch_issue_admin')},
                {'label': 'Create Report', 'url': reverse('main:create_report')},
                {'label': 'My Activity', 'url': reverse('main:my_activity')},
                {'label': 'Notifications', 'url': reverse('main:notification')},
            ],
            'Moderator': [
                {'label': 'Assigned Issues', 'url': reverse('main:fetch_issue_admin')},
                {'label': 'Issue Management', 'url': reverse('main:issue_management')},
                {'label': 'Priority Queue', 'url': reverse('main:priority_queue')},
                {'label': 'Reports', 'url': reverse('main:reports_overview')},
                {'label': 'Notifications', 'url': reverse('main:notification')},
            ],
            'Super Admin': [
                {'label': 'All Issues', 'url': reverse('main:fetch_issue_admin')},
                {'label': 'Issue Management', 'url': reverse('main:issue_management')},
                {'label': 'User Management', 'url': reverse('main:User_detail')},
                {'label': 'AI Review Queue', 'url': reverse('main:ai-review')},
                {'label': 'Settings', 'url': reverse('main:settings')},
            ],
            'Admin User': [
                {'label': 'Issue Feed', 'url': reverse('main:fetch_issue_admin')},
                {'label': 'Issue Management', 'url': reverse('main:issue_management')},
                {'label': 'Priority Queue', 'url': reverse('main:priority_queue')},
                {'label': 'Notifications', 'url': reverse('main:notification')},
            ],
        }
        return mapping.get(role_name, mapping['Simple User'])

    if stat.get('err'):
        fallback_role = request.session.get('utype') or 'Simple User'
        fallback_details = {
            'Full_Name': request.session.get('fname') or username,
            'UserName': username,
            'EmailID': request.session.get('user_email') or username,
            'UserRole': fallback_role,
            'Status': 'Activated',
        }
        return themed_render(
            request,
            'main/profile.html',
            {
                'err': stat['err'],
                'user_details': fallback_details,
                'issues_count': 0,
                'page_msg': page_msg,
                'role_feature_links': role_links(fallback_role),
            },
        )

    user_details = stat.get('user_details', {})

    issues_count = 0
    try:
        issues_count = len(CivilOperation().fetch_issues(username))
    except Exception:
        issues_count = 0

    current_role = request.session.get('utype') or user_details.get('UserRole') or 'Simple User'
    context = {
        'user_details': user_details,
        'issues_count': issues_count,
        'page_msg': page_msg,
        'err': page_err,
        'role_feature_links': role_links(current_role),
    }

    return themed_render(request, 'main/profile.html', context)

@csrf_exempt
def notification(request):
    if 'user' not in request.session:
        return redirect('main:login')

    username = request.session.get('user')
    utype = request.session.get('utype')
    is_admin_user = has_admin_panel_access(utype)
    notif_op = NotificationOperation()
    page_msg = None
    page_err = None
    active_filter = (request.GET.get('filter') or request.POST.get('filter') or 'all').strip().lower()
    if active_filter not in {'all', 'unread', 'read'}:
        active_filter = 'all'

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'mark_all_read':
            stat = notif_op.mark_all_as_read(username)
            if stat.get('msg'):
                page_msg = stat.get('msg')
            else:
                page_err = stat.get('err') or 'Failed to update notifications.'
        elif action == 'delete_notification':
            notification_id = (request.POST.get('notification_id') or '').strip()
            stat = notif_op.delete_notification(notification_id, username)
            if stat.get('msg'):
                page_msg = stat.get('msg')
            else:
                page_err = stat.get('err') or 'Failed to delete notification.'
        elif action == 'mark_as_read':
            notification_id = (request.POST.get('notification_id') or '').strip()
            stat = notif_op.mark_as_read(notification_id, username)
            if stat.get('msg'):
                page_msg = stat.get('msg')
            else:
                page_err = stat.get('err') or 'Failed to update notification.'
        elif action == 'mark_selected_read':
            selected_ids = request.POST.getlist('selected_ids')
            updated = 0
            for notification_id in selected_ids:
                stat = notif_op.mark_as_read((notification_id or '').strip(), username)
                if stat.get('msg'):
                    updated += 1
            if updated:
                page_msg = f'{updated} notification(s) marked as read.'
            else:
                page_err = 'No notifications were updated.'
        elif action == 'delete_selected':
            selected_ids = request.POST.getlist('selected_ids')
            deleted = 0
            for notification_id in selected_ids:
                stat = notif_op.delete_notification((notification_id or '').strip(), username)
                if stat.get('msg'):
                    deleted += 1
            if deleted:
                page_msg = f'{deleted} notification(s) deleted successfully.'
            else:
                page_err = 'No notifications were deleted.'

    notif_data = notif_op.fetch_notifications(username)
    unread_count = notif_op.unread_count(username)

    notifications = []
    if notif_data and notif_data.get('notifications'):
        notifications = notif_data['notifications']

    all_count = len(notifications)
    read_count = sum(1 for n in notifications if n.get('is_read'))
    unread_count = all_count - read_count

    if active_filter == 'unread':
        filtered_notifications = [n for n in notifications if not n.get('is_read')]
    elif active_filter == 'read':
        filtered_notifications = [n for n in notifications if n.get('is_read')]
    else:
        filtered_notifications = notifications

    paginator = Paginator(filtered_notifications, 10)
    page_number = request.GET.get('page') or request.POST.get('page') or 1
    page_obj = paginator.get_page(page_number)

    request.session['unread_notifications'] = unread_count

    template_name = 'main/system_notifications.html' if is_admin_user else 'main/notifications.html'

    return themed_render(
        request,
        template_name,
        {
            'notifications': page_obj.object_list,
            'page_obj': page_obj,
            'active_filter': active_filter,
            'all_count': all_count,
            'read_count': read_count,
            'unread_count': unread_count,
            'username': username,
            'is_admin_user': is_admin_user,
            'msg': page_msg,
            'err': page_err,
        }
    )

# ---------------------------------------------------------------------------
# Admin / Moderator / Editor Views
# ---------------------------------------------------------------------------
@csrf_exempt
def fetch_issue_admin(request):
    # 🔒 Authentication check
    if 'user' not in request.session:
        return redirect('main:login')

    # 🔒 Authorization check
    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        return redirect('main:index')

    try:
        model = CivilOperation()

        # ✅ Fetch ALL issues for admin (no limit)
        issues_result = model.fetch_all_issues(
            username=request.session.get('user'),
            utype=request.session.get('utype'),
            limit=0  # 0 or large number → fetch all
        )
        issues = issues_result.get('issues', []) if isinstance(issues_result, dict) else issues_result

    except Exception as e:
        print("View Error in fetch_issue_admin:", str(e))
        issues = []

    # ✅ Send data to template
    return themed_render(
        request,
        'main/fetch_issue.html',
        {
            'issues': issues
        }
    )


@csrf_exempt
def reports(request):
    if 'user' not in request.session:
        return redirect('main:login')

    data = CivilOperation().get_reports_data(days=30)
    return themed_render(request, 'main/reports.html', data)


@csrf_exempt
def priority_queue(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    username = request.session.get('user')
    utype = request.session.get('utype')

    issues_result = CivilOperation().fetch_all_issues(username=username, utype=utype, limit=0)
    raw_issues = issues_result.get('issues', []) if isinstance(issues_result, dict) else issues_result

    priority_levels = {'critical', 'high', 'urgent'}
    priority_issues = []
    for issue in raw_issues or []:
        urgency = (issue.get('Urgency') or issue.get('urgency') or '').strip()
        urgency_key = urgency.lower()
        if urgency_key in priority_levels or any(tag in urgency_key for tag in ['critical', 'high', 'urgent']):
            priority_issues.append({
                'issue_id': issue.get('IssueID') or issue.get('issue_id'),
                'title': issue.get('Title') or issue.get('title') or 'Untitled',
                'category': issue.get('Category') or issue.get('category') or 'Uncategorized',
                'urgency': urgency or 'High',
                'status': issue.get('Status') or issue.get('status') or 'Pending',
                'location': issue.get('Location') or issue.get('location') or 'Unknown',
                'reported_by': issue.get('ReportedBy') or issue.get('reported_by') or issue.get('reporter') or 'Unknown',
                'issue_date': issue.get('IssueDate'),
            })

    urgency_counts = {'critical': 0, 'high': 0, 'urgent': 0}
    for issue in priority_issues:
        key = (issue.get('urgency') or '').strip().lower()
        if 'critical' in key:
            urgency_counts['critical'] += 1
        elif 'urgent' in key:
            urgency_counts['urgent'] += 1
        else:
            urgency_counts['high'] += 1

    sla_days = 7
    sla_breach_count = 0
    now = datetime.now()
    for issue in priority_issues:
        status = (issue.get('status') or '').strip().lower()
        if status == 'resolved':
            continue
        issue_date = issue.get('issue_date')
        if isinstance(issue_date, datetime) and (now - issue_date).days >= sla_days:
            sla_breach_count += 1

    category_counts = {}
    for issue in priority_issues:
        cat = issue.get('category') or 'Uncategorized'
        category_counts[cat] = category_counts.get(cat, 0) + 1
    top_category = None
    top_category_count = 0
    if category_counts:
        top_category, top_category_count = max(category_counts.items(), key=lambda x: x[1])

    paginator = Paginator(priority_issues, 10)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    paginated_issues = list(page_obj.object_list)

    page_start = page_obj.start_index() if paginator.count else 0
    page_end = page_obj.end_index() if paginator.count else 0
    page_window_start = max(page_obj.number - 2, 1)
    page_window_end = min(page_obj.number + 2, paginator.num_pages) if paginator.num_pages else 1
    page_numbers = list(range(page_window_start, page_window_end + 1))

    return themed_render(
        request,
        'main/priority_queue.html',
        {
            'priority_issues': paginated_issues,
            'priority_count': len(priority_issues),
            'sla_breach_count': sla_breach_count,
            'sla_days': sla_days,
            'top_category': top_category,
            'top_category_count': top_category_count,
            'critical_count': urgency_counts['critical'],
            'high_count': urgency_counts['high'],
            'urgent_count': urgency_counts['urgent'],
            'page_obj': page_obj,
            'page_numbers': page_numbers,
            'page_start': page_start,
            'page_end': page_end,
            'total_issues': paginator.count,
        }
    )


@csrf_exempt
def work_orders(request):
    if 'user' not in request.session:
        return redirect('main:login')

    return themed_render(request, 'main/work_orders.html')


@csrf_exempt
def reports_performance(request):
    if 'user' not in request.session:
        return redirect('main:login')

    return themed_render(request, 'main/reports_performance.html')


@csrf_exempt
def reports_analytics(request):
    if 'user' not in request.session:
        return redirect('main:login')

    data = CivilOperation().get_reports_data(days=30)
    return themed_render(request, 'main/reports_analytics.html', data)


@csrf_exempt
def reports_overview(request):
    if 'user' not in request.session:
        return redirect('main:login')

    return themed_render(request, 'main/reports_overview.html')


@csrf_exempt
def create_report(request):
    if 'user' not in request.session:
        return redirect('main:login')

    context = {}

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        priority = (request.POST.get('priority') or '').strip()
        category = (request.POST.get('category') or '').strip()
        location = (request.POST.get('location') or '').strip()
        due_date = (request.POST.get('due_date') or '').strip()
        summary = (request.POST.get('summary') or '').strip()
        findings = (request.POST.get('findings') or '').strip()
        reviewer_notes = (request.POST.get('reviewer_notes') or '').strip()

        if not title or not summary or not findings:
            context['err'] = 'Title, summary, and findings are required.'
        else:
            try:
                client = MongoClient(django_settings.MONGO_URI)
                db = client['CivilOperation']
                coll = db['Reports']

                last_report = coll.find_one(sort=[('ReportID', -1)])
                if last_report and last_report.get('ReportID'):
                    try:
                        last_id = int(last_report['ReportID'].split('-')[1])
                        report_id = f"RPT-{str(last_id + 1).zfill(3)}"
                    except Exception:
                        report_id = f"RPT-{datetime.now().strftime('%y%m%d%H%M%S')}"
                else:
                    report_id = "RPT-001"

                attachments = []
                files = request.FILES.getlist('attachments')
                if files:
                    fs = FileSystemStorage()
                    for file_obj in files:
                        ext = os.path.splitext(file_obj.name)[1]
                        unique_filename = f"Reports/{uuid.uuid4()}{ext}"
                        saved_name = fs.save(unique_filename, file_obj)
                        attachments.append(fs.url(saved_name))

                doc = {
                    'ReportID': report_id,
                    'Title': title,
                    'Priority': priority or 'Standard',
                    'Category': category or 'General',
                    'Location': location,
                    'DueDate': due_date,
                    'Summary': summary,
                    'Findings': findings,
                    'ReviewerNotes': reviewer_notes,
                    'Attachments': attachments,
                    'Status': 'Draft',
                    'CreatedBy': request.session.get('user'),
                    'CreatedByEmail': request.session.get('user_email') or request.session.get('user'),
                    'CreatedByRole': request.session.get('utype') or 'Editor',
                    'Created_At': datetime.now(),
                }

                coll.create_index('ReportID', unique=True)
                coll.insert_one(doc)

                context['msg'] = 'Report saved successfully.'
            except Exception as e:
                context['err'] = f'Failed to save report: {e}'

    return themed_render(request, 'main/create_report.html', context)


@csrf_exempt
def my_activity(request):
    if 'user' not in request.session:
        return redirect('main:login')
    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    current_role = request.session.get('utype')
    if current_role != 'Editor':
        return redirect(f"{reverse('main:index')}?err=Editor+activity+is+only+available+for+Editor+role.")

    username = request.session.get('user')
    user_email = request.session.get('user_email') or username
    username_pattern = {'$regex': f'^{re.escape(str(username or "").strip())}$', '$options': 'i'}
    email_pattern = {'$regex': f'^{re.escape(str(user_email or "").strip())}$', '$options': 'i'}

    context = {
        'recent_reports': [],
        'recent_issues': [],
        'activity_timeline': [],
        'report_count': 0,
        'draft_count': 0,
        'approval_pending_count': 0,
        'notification_count': 0,
    }

    timeline = []

    try:
        client = MongoClient(django_settings.MONGO_URI)
        db = client['CivilOperation']
        report_coll = db['Reports']

        reports_query = {
            '$or': [
                {'CreatedBy': username_pattern},
                {'CreatedByEmail': email_pattern},
            ]
        }
        report_projection = {
            '_id': 0,
            'ReportID': 1,
            'Title': 1,
            'Category': 1,
            'Priority': 1,
            'Status': 1,
            'Created_At': 1,
            'DueDate': 1,
        }
        report_rows = list(report_coll.find(reports_query, report_projection).sort('Created_At', -1).limit(50))

        mapped_reports = []
        for row in report_rows:
            created_at = row.get('Created_At')
            status = (row.get('Status') or 'Draft').strip()
            mapped = {
                'report_id': row.get('ReportID') or '',
                'title': row.get('Title') or 'Untitled report',
                'category': row.get('Category') or 'General',
                'priority': row.get('Priority') or 'Standard',
                'status': status,
                'status_key': status.lower(),
                'created_at': created_at,
                'due_date': row.get('DueDate') or '',
            }
            mapped_reports.append(mapped)

            if isinstance(created_at, datetime):
                timeline.append({
                    'kind': 'report',
                    'title': f"Report created: {mapped['title']}",
                    'meta': f"{mapped['report_id']} • {mapped['status']}",
                    'status': mapped['status'],
                    'timestamp': created_at,
                })

        context['recent_reports'] = mapped_reports[:8]
        context['report_count'] = len(mapped_reports)
        context['draft_count'] = sum(1 for item in mapped_reports if item.get('status_key') == 'draft')
        context['approval_pending_count'] = sum(
            1 for item in mapped_reports if item.get('status_key') in {'pending', 'in review', 'review'}
        )
    except Exception as e:
        print('View Error in My Activity (Reports):', str(e))

    try:
        issues_result = CivilOperation().fetch_all_issues(username=username, utype=current_role, limit=0)
        raw_issues = issues_result.get('issues', []) if isinstance(issues_result, dict) else issues_result

        user_issues = []
        user_identity = str(username or '').strip().lower()
        for issue in raw_issues or []:
            reporter = str(issue.get('ReportedBy') or issue.get('reported_by') or issue.get('reporter') or '').strip()
            if reporter.lower() != user_identity:
                continue
            issue_date = issue.get('IssueDate')
            mapped_issue = {
                'issue_id': issue.get('IssueID') or issue.get('issue_id') or '',
                'title': issue.get('Title') or issue.get('title') or 'Untitled issue',
                'status': issue.get('Status') or issue.get('status') or 'Pending',
                'urgency': issue.get('Urgency') or issue.get('urgency') or 'Medium',
                'category': issue.get('Category') or issue.get('category') or 'Uncategorized',
                'issue_date': issue_date,
            }
            user_issues.append(mapped_issue)

            if isinstance(issue_date, datetime):
                timeline.append({
                    'kind': 'issue',
                    'title': f"Issue reported: {mapped_issue['title']}",
                    'meta': f"{mapped_issue['issue_id']} • {mapped_issue['status']}",
                    'status': mapped_issue['urgency'],
                    'timestamp': issue_date,
                })

        user_issues.sort(key=lambda x: x.get('issue_date') or datetime.min, reverse=True)
        context['recent_issues'] = user_issues[:6]
    except Exception as e:
        print('View Error in My Activity (Issues):', str(e))

    try:
        notifications_result = NotificationOperation().fetch_notifications(username)
        notifications = notifications_result.get('notifications', []) if isinstance(notifications_result, dict) else []
        context['notification_count'] = len(notifications)

        for item in notifications[:10]:
            created_at = item.get('created_at')
            if not isinstance(created_at, datetime):
                continue
            timeline.append({
                'kind': 'notification',
                'title': item.get('category') or 'System Alert',
                'meta': item.get('message') or '',
                'status': 'Unread' if not item.get('is_read') else 'Read',
                'timestamp': created_at,
            })
    except Exception as e:
        print('View Error in My Activity (Notifications):', str(e))

    timeline.sort(key=lambda x: x.get('timestamp') or datetime.min, reverse=True)
    context['activity_timeline'] = timeline[:15]

    return themed_render(request, 'main/my_activity.html', context)


@csrf_exempt
def reports_data(request):
    if 'user' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    start = request.GET.get('start')
    end = request.GET.get('end')
    category = request.GET.get('category') or None
    status = request.GET.get('status') or None

    start_date = None
    end_date = None
    try:
        if start:
            start_date = datetime.strptime(start, "%Y-%m-%d")
        if end:
            end_date = datetime.strptime(end, "%Y-%m-%d")
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    except Exception:
        start_date = None
        end_date = None

    data = CivilOperation().get_reports_data(
        days=30,
        start_date=start_date,
        end_date=end_date,
        category=category,
        status=status
    )
    return JsonResponse(data)

@csrf_exempt
def issue_management(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        return redirect('main:index')

    obj = CivilOperation()
    current_role = request.session.get('utype')
    can_assign_issue = current_role in ['Super Admin', 'Moderator', 'Admin User']

    if request.method == 'POST':
        issue_id = request.POST.get('issue_id')
        action = request.POST.get('action')
        if issue_id and action:
            if action == 'approve':
                obj.update_issue_status(issue_id, 'In Review')
            elif action == 'reject':
                obj.update_issue_status(issue_id, 'Rejected')
            elif action == 'assign':
                if not can_assign_issue:
                    return redirect('main:issue_management')
                authority = request.POST.get('authority')
                if authority:
                    obj.update_issue_assignment(issue_id, authority)
                    obj.update_issue_status(issue_id, 'In Progress')

    issues_result = obj.fetch_all_issues(
        username=request.session.get('user'),
        utype=request.session.get('utype'),
        limit=0
    )
    raw_issues = issues_result.get('issues', []) if isinstance(issues_result, dict) else issues_result

    mapped_issues = []
    for i in raw_issues:
        mapped_issues.append({
            'issue_id': i.get('IssueID') or i.get('issue_id'),
            'title': i.get('Title') or i.get('title'),
            'category': i.get('Category') or i.get('category'),
            'severity': i.get('Urgency') or i.get('severity') or 'Low',
            'status': i.get('Status') or i.get('status') or 'Reported',
            'reporter': i.get('ReportedBy') or i.get('reporter') or 'Unknown',
            'department': i.get('Department') or i.get('department'),
            'image': i.get('Image') or i.get('image')
        })

    def issue_seq(value):
        raw = str(value or '')
        try:
            return int(raw.split('-')[-1])
        except Exception:
            return 0

    # Keep list in predictable IssueID sequence
    mapped_issues.sort(key=lambda x: issue_seq(x.get('issue_id')))

    current_tab = request.GET.get('tab') or 'All Issues'
    status_map = {
        'All Issues': [],
        'Reported': ['Reported', 'Pending'],
        'In Review': ['In Review'],
        'In Progress': ['In Progress'],
        'Resolved': ['Resolved'],
        'Rejected': ['Rejected']
    }
    allowed_statuses = status_map.get(current_tab, [])

    if allowed_statuses:
        mapped_issues = [i for i in mapped_issues if i.get('status') in allowed_statuses]

    paginator = Paginator(mapped_issues, 10)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    paginated_issues = list(page_obj.object_list)

    page_start = page_obj.start_index() if paginator.count else 0
    page_end = page_obj.end_index() if paginator.count else 0
    page_window_start = max(page_obj.number - 2, 1)
    page_window_end = min(page_obj.number + 2, paginator.num_pages) if paginator.num_pages else 1
    page_numbers = list(range(page_window_start, page_window_end + 1))

    def normalize_status(s):
        if s in ['Reported', 'Pending']:
            return 'reported'
        if s == 'In Review':
            return 'in_review'
        if s == 'In Progress':
            return 'in_progress'
        if s == 'Resolved':
            return 'resolved'
        if s == 'Rejected':
            return 'rejected'
        return 'reported'

    status_counts = {
        'reported': 0,
        'in_review': 0,
        'in_progress': 0,
        'resolved': 0,
        'rejected': 0
    }
    for i in raw_issues:
        status_counts[normalize_status(i.get('Status'))] += 1

    authorities = [
        'Roads Dept',
        'Water Works',
        'Electricity Board',
        'Sanitation Unit',
        'Drainage Team'
    ]

    return themed_render(
        request,
        'main/manage_issue.html',
        {
            'issues': paginated_issues,
            'current_tab': current_tab,
            'status_counts': status_counts,
            'authorities': authorities,
            'can_assign_issue': can_assign_issue,
            'page_obj': page_obj,
            'page_numbers': page_numbers,
            'total_issues': paginator.count,
            'page_start': page_start,
            'page_end': page_end
        }
    )

@csrf_exempt
def User_detail(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        return redirect('main:index')

    user_op = UserOperation()

    page_msg = None
    page_err = None

    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')
        if action == 'bulk_update':
            bulk_action = (request.POST.get('bulk_action') or '').strip()
            selected_user_ids = request.POST.getlist('selected_user_ids')

            if not selected_user_ids:
                page_err = 'Please select at least one user for bulk action.'
            else:
                success_count = 0
                for selected_user_id in selected_user_ids:
                    if bulk_action == 'activate':
                        stat = user_op.update_admin_status(selected_user_id, 'Activated')
                    elif bulk_action == 'suspend':
                        stat = user_op.update_admin_status(selected_user_id, 'Suspended')
                    elif bulk_action == 'delete':
                        stat = user_op.delete_admin_user(selected_user_id)
                    else:
                        stat = {'err': 'Invalid bulk action selected.'}

                    if stat.get('msg') and not stat.get('err'):
                        success_count += 1

                if bulk_action not in ['activate', 'suspend', 'delete']:
                    page_err = 'Invalid bulk action selected.'
                elif success_count:
                    page_msg = f'Bulk action completed for {success_count} user(s).'
                else:
                    page_err = 'No users were updated. Please try again.'

        if action and user_id:
            if action == 'edit_role':
                new_role = (request.POST.get('role') or '').strip()
                if new_role:
                    stat = user_op.update_admin_role(user_id, new_role)
                    if stat.get('msg'):
                        page_msg = stat.get('msg')
                    elif stat.get('err'):
                        page_err = stat.get('err')
            elif action == 'toggle_status':
                current = request.POST.get('current_status') or 'Activated'
                new_status = 'Suspended' if current == 'Activated' else 'Activated'
                stat = user_op.update_admin_status(user_id, new_status)
                if stat.get('msg'):
                    page_msg = stat.get('msg')
                elif stat.get('err'):
                    page_err = stat.get('err')
            elif action == 'delete':
                stat = user_op.delete_admin_user(user_id)
                if stat.get('msg'):
                    page_msg = stat.get('msg')
                elif stat.get('err'):
                    page_err = stat.get('err')

    search = request.GET.get('q') or None
    role = request.GET.get('role') or None
    status = request.GET.get('status') or None

    users_result = user_op.fetch_all_users(search=search, role=role, status=status)
    raw_users = users_result.get('users', []) if isinstance(users_result, dict) else users_result

    users = []
    for u in raw_users:
        users.append({
            'user_id': u.get('User_ID') or u.get('UserId') or u.get('Authority_ID') or u.get('_id'),
            'avatar': u.get('Avatar'),
            'name': u.get('Full_Name') or u.get('UserName'),
            'email': u.get('EmailID'),
            'role': u.get('UserRole') or u.get('AdminRole') or 'Simple User',
            'status': u.get('Status') or 'Activated',
            'joined': u.get('Created_At')
        })

    role_priority = {
        'Super Admin': 1,
        'Moderator': 2,
        'Editor': 3,
        'Authority': 4,
        'Support': 5,
        'Simple User': 6,
        'Admin User': 7
    }
    users.sort(key=lambda x: (role_priority.get(x.get('role') or '', 99), (x.get('name') or '').lower()))
    grouped_users = {}
    for user in users:
        role_name = user.get('role') or 'Unassigned'
        grouped_users.setdefault(role_name, []).append(user)

    grouped_user_tables = []
    for role_name in sorted(grouped_users.keys(), key=lambda r: (role_priority.get(r, 99), r.lower())):
        grouped_user_tables.append({
            'role': role_name,
            'users': grouped_users[role_name],
        })

    return themed_render(
        request,
        'main/user_management.html',
        {
            'users': users,
            'grouped_user_tables': grouped_user_tables,
            'search': search or '',
            'role_filter': role or '',
            'status_filter': status or '',
            'is_super_admin': request.session.get('utype') == 'Super Admin',
            'msg': page_msg,
            'err': page_err,
        }
    )


@csrf_exempt
def export_users_pdf(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        return redirect('main:index')

    search = request.GET.get('q') or None
    role = request.GET.get('role') or None
    status = request.GET.get('status') or None

    user_op = UserOperation()
    users_result = user_op.fetch_all_users(search=search, role=role, status=status)
    raw_users = users_result.get('users', []) if isinstance(users_result, dict) else users_result

    users = []
    for u in raw_users:
        users.append({
            'user_id': u.get('User_ID') or u.get('UserId') or u.get('Authority_ID') or '',
            'name': u.get('Full_Name') or u.get('UserName') or '',
            'email': u.get('EmailID') or '',
            'role': u.get('UserRole') or u.get('AdminRole') or 'Simple User',
            'status': u.get('Status') or 'Activated',
            'joined': u.get('Created_At')
        })

    role_priority = {
        'Super Admin': 1,
        'Moderator': 2,
        'Editor': 3,
        'Authority': 4,
        'Support': 5,
        'Simple User': 6,
        'Admin User': 7
    }
    users.sort(key=lambda x: (role_priority.get(x.get('role') or '', 99), (x.get('name') or '').lower()))

    logo_url = request.build_absolute_uri(
        f"{django_settings.STATIC_URL.rstrip('/')}/assets/images/logo_without_bg.png"
    )
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    grouped_users = {}
    for user in users:
        role_name = user.get('role') or 'Unassigned'
        grouped_users.setdefault(role_name, []).append(user)

    grouped_tables_html = []
    if grouped_users:
        for role_name in sorted(grouped_users.keys(), key=lambda r: (role_priority.get(r, 99), r.lower())):
            role_rows = []
            for idx, user in enumerate(grouped_users[role_name], start=1):
                joined_value = user['joined'].strftime('%Y-%m-%d') if hasattr(user['joined'], 'strftime') else ''
                role_rows.append(
                    f"""
                    <tr>
                      <td>{idx}</td>
                      <td>{escape(str(user.get('user_id') or ''))}</td>
                      <td>{escape(str(user.get('name') or ''))}</td>
                      <td>{escape(str(user.get('email') or ''))}</td>
                      <td>{escape(str(user.get('status') or ''))}</td>
                      <td>{escape(joined_value)}</td>
                    </tr>
                    """
                )
            grouped_tables_html.append(
                f"""
                <section class="role-section">
                  <h2 class="role-title">{escape(role_name)} ({len(grouped_users[role_name])})</h2>
                  <table>
                    <thead>
                      <tr>
                        <th style="width:6%;">#</th>
                        <th style="width:16%;">User ID</th>
                        <th style="width:20%;">Name</th>
                        <th style="width:33%;">Email</th>
                        <th style="width:13%;">Status</th>
                        <th style="width:12%;">Joined</th>
                      </tr>
                    </thead>
                    <tbody>
                      {''.join(role_rows)}
                    </tbody>
                  </table>
                </section>
                """
            )
    else:
        grouped_tables_html.append('<p style="text-align:center; margin-top: 20px;">No users found.</p>')

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title></title>
        <style>
          @page {{
            size: A4;
            margin: 0;
          }}

          :root {{
            --ink: #0f172a;
            --muted: #475569;
            --line: #cbd5e1;
            --head1: #0f172a;
            --head2: #1d4ed8;
            --accent: #0ea5e9;
            --paper: #ffffff;
            --page-bg: #edf3ff;
          }}

          * {{
            box-sizing: border-box;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }}

          body {{
            margin: 0;
            font-family: "Segoe UI", Arial, sans-serif;
            background:
              radial-gradient(circle at 15% 10%, #dbeafe 0%, transparent 35%),
              radial-gradient(circle at 90% 20%, #bfdbfe 0%, transparent 30%),
              linear-gradient(120deg, #f8fbff 0%, var(--page-bg) 100%);
            color: var(--ink);
          }}

          .page {{
            width: 210mm;
            min-height: 297mm;
            margin: 0 auto 22mm;
            padding: 13mm;
            background: var(--paper);
            border-radius: 12px;
            box-shadow: 0 8px 30px rgba(15, 23, 42, 0.12);
            position: relative;
            overflow: hidden;
            display: flex;
          }}

          .page::before {{
            content: "";
            position: absolute;
            inset: 0;
            background-image: url('{logo_url}');
            background-repeat: no-repeat;
            background-position: center 56%;
            background-size: 44%;
            opacity: 0.07;
            pointer-events: none;
          }}

          .page::after {{
            content: "";
            position: absolute;
            inset: 0;
            background:
              linear-gradient(145deg, rgba(255,255,255,0.62), rgba(255,255,255,0.2));
            pointer-events: none;
          }}

          .content {{
            position: relative;
            z-index: 2;
            width: 100%;
            min-height: calc(297mm - 26mm);
            display: flex;
            flex-direction: column;
          }}

          .header {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
            padding: 10px 12px;
            border: 1px solid #dbeafe;
            border-radius: 12px;
            background: linear-gradient(135deg, #eff6ff, #dbeafe);
          }}

          .title {{
            margin: 0;
            font-size: 22px;
            font-weight: 800;
            letter-spacing: 0.3px;
            color: var(--head1);
          }}

          .subtitle {{
            margin: 6px 0 0;
            font-size: 12px;
            color: var(--muted);
          }}

          .pill {{
            white-space: nowrap;
            align-self: center;
            border-radius: 999px;
            padding: 7px 12px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.2px;
            color: #e0f2fe;
            background: linear-gradient(135deg, #0f172a, #1e3a8a);
          }}

          table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 11px;
            border-radius: 10px;
            overflow: hidden;
            background: #ffffff;
          }}

          .table-wrap {{
            flex: 1;
          }}

          .role-section {{
            margin-bottom: 12px;
            break-inside: avoid;
            page-break-inside: avoid;
          }}

          .role-title {{
            margin: 0 0 6px;
            font-size: 13px;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: 0.2px;
          }}

          th, td {{
            border: 1px solid var(--line);
            padding: 7px 6px;
            text-align: left;
            vertical-align: top;
            word-break: break-word;
          }}

          th {{
            color: #ffffff;
            font-size: 11px;
            letter-spacing: 0.25px;
            background: linear-gradient(135deg, var(--head1), var(--head2));
          }}

          tbody tr:nth-child(even) {{
            background: #f8fbff;
          }}

          .report-footer {{
            margin-top: 12px;
            border-top: 1px solid #dbeafe;
            padding-top: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            font-size: 11px;
            color: #334155;
          }}

          .report-footer .left {{
            font-weight: 600;
            color: #0f172a;
          }}

          .report-footer .right {{
            color: #475569;
          }}

          .print-wrap {{
            position: fixed;
            left: 50%;
            bottom: 18px;
            transform: translateX(-50%);
            z-index: 10;
          }}

          .print-btn {{
            border: 0;
            border-radius: 999px;
            background: linear-gradient(135deg, #0f172a, #1d4ed8);
            color: #ffffff;
            padding: 11px 26px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.2px;
            cursor: pointer;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.25);
          }}

          .print-btn:hover {{
            filter: brightness(1.05);
          }}

          @media print {{
            html, body {{
              -webkit-print-color-adjust: exact !important;
              print-color-adjust: exact !important;
            }}

            body {{
              background: #ffffff;
            }}

            .page {{
              width: auto;
              min-height: auto;
              margin: 0;
              padding: 13mm;
              border-radius: 0;
              box-shadow: none;
            }}

            .no-print {{
              display: none !important;
            }}
          }}
        </style>
      </head>
      <body>
        <div class="page">
          <div class="content">
            <div class="header">
              <div>
                <h1 class="title">Fixora User Management Report</h1>
                <p class="subtitle">Generated at: {escape(generated_at)}</p>
              </div>
              <span class="pill">A4 Print Layout</span>
            </div>

            <div class="table-wrap">{''.join(grouped_tables_html)}</div>

            <div class="report-footer">
              <span class="left">Fixora Civic AI Platform</span>
              <span class="right">Confidential User Management Snapshot</span>
            </div>
          </div>
        </div>

        <div class="print-wrap no-print">
          <button type="button" class="print-btn" onclick="window.print()">Print</button>
        </div>
        <script>
          (function() {{
            var originalTitle = document.title;
            window.addEventListener('beforeprint', function() {{
              document.title = '';
            }});
            window.addEventListener('afterprint', function() {{
              document.title = originalTitle;
            }});
          }})();
        </script>
      </body>
    </html>
    """
    return HttpResponse(html)
    

# ---------------------------------------------------------------------------
# ML Training
# ---------------------------------------------------------------------------
@csrf_exempt
def train_issue_ml_model(request):
    """
    Train a baseline ML model on Issue text data.
    Default target is Category; also supports Urgency and Status.

    Request:
    - Method: GET or POST
    - target: Category | Urgency | Status (optional, default Category)
    - min_samples: minimum rows required (optional, default 30)
    """
    is_page_trigger = request.method == 'GET'
    ui_preview_mode = request.method == 'GET' and request.GET.get('view') == '1'
    is_training_request = (
        request.method == 'POST'
        or request.GET.get('action') == 'train'
        or request.GET.get('target')
        or request.GET.get('min_samples')
    )

    # Optional preview mode: only when explicitly requested.
    if ui_preview_mode and not is_training_request:
        latest_metadata = get_latest_training_metadata()
        return themed_render(
            request,
            'main/train_issue_model.html',
            {
                'training_metadata': latest_metadata,
            },
        )

    def redirect_back(msg=None, err=None):
        back_url = request.META.get('HTTP_REFERER')
        if not back_url:
            return redirect('main:index')

        parts = list(urlsplit(back_url))
        query = dict(parse_qsl(parts[3], keep_blank_values=True))
        if msg:
            query['msg'] = msg
            query.pop('err', None)
        if err:
            query['err'] = err
            query.pop('msg', None)
        parts[3] = urlencode(query)
        return redirect(urlunsplit(parts))

    if 'user' not in request.session:
        if is_page_trigger:
            return redirect('main:login')
        return JsonResponse({'err': 'Unauthorized. Please login.'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_admin_panel_access(request.session.get('utype')):
        if is_page_trigger:
            return redirect('main:index')
        return JsonResponse({'err': 'Forbidden. Admin access required.'}, status=403)

    # Daily limiter: max 5 successful trainings per user per day.
    training_actor = str(request.session.get('user') or 'anonymous').strip().lower()
    today_key = timezone.localdate().isoformat()
    daily_limit = 5
    train_count_key = f'fixora:ml_train_count:{training_actor}:{today_key}'
    used_today = int(cache.get(train_count_key, 0) or 0)
    if used_today >= daily_limit:
        limit_msg = f'Daily training limit reached ({daily_limit}/day). Try again tomorrow.'
        if is_page_trigger:
            return redirect_back(err=limit_msg)
        return JsonResponse({'err': limit_msg, 'daily_limit': daily_limit}, status=429)

    payload = request.POST if request.method == 'POST' else request.GET

    target_field = (payload.get('target') or 'Category').strip()
    if target_field not in ['Category', 'Urgency', 'Status']:
        if is_page_trigger:
            return redirect_back(err='Invalid target. Use Category, Urgency, or Status.')
        return JsonResponse({'err': 'Invalid target. Use Category, Urgency, or Status.'}, status=400)

    try:
        min_samples = int(payload.get('min_samples') or 30)
    except Exception:
        min_samples = 30

    try:
        client = MongoClient(django_settings.MONGO_URI)
        issue_coll = client['CivilOperation']['Issue']

        projection = {
            '_id': 0,
            'IssueID': 1,
            'Title': 1,
            'Description': 1,
            'Category': 1,
            'Urgency': 1,
            'Status': 1,
            'Location': 1,
            'Department': 1,
        }
        rows = list(issue_coll.find({}, projection))

        texts = []
        labels = []
        for row in rows:
            label = (row.get(target_field) or '').strip()
            if not label:
                continue
            title = (row.get('Title') or '').strip()
            desc = (row.get('Description') or '').strip()
            location = (row.get('Location') or '').strip()
            department = (row.get('Department') or '').strip()

            text = " ".join([title, desc, location, department]).strip()
            if not text:
                continue

            texts.append(text)
            labels.append(label)

        if len(texts) < min_samples:
            if is_page_trigger:
                return redirect_back(err='Not enough training data.')
            return JsonResponse(
                {
                    'err': 'Not enough training data.',
                    'target': target_field,
                    'samples_found': len(texts),
                    'min_samples_required': min_samples
                },
                status=400
            )

        class_counts = Counter(labels)
        valid_labels = {k for k, v in class_counts.items() if v >= 2}
        filtered_texts = []
        filtered_labels = []
        for x, y in zip(texts, labels):
            if y in valid_labels:
                filtered_texts.append(x)
                filtered_labels.append(y)

        if len(valid_labels) < 2:
            if is_page_trigger:
                return redirect_back(err='Need at least 2 classes with >=2 samples each.')
            return JsonResponse(
                {
                    'err': 'Need at least 2 classes with >=2 samples each.',
                    'class_distribution': class_counts
                },
                status=400
            )

        unique_class_count = len(set(filtered_labels))
        total_samples = len(filtered_labels)
        test_count = max(unique_class_count, int(round(total_samples * 0.2)))
        if test_count >= total_samples:
            test_count = max(1, total_samples - 1)

        X_train, X_test, y_train, y_test = train_test_split(
            filtered_texts,
            filtered_labels,
            test_size=test_count,
            random_state=42,
            stratify=filtered_labels
        )

        model = Pipeline([
            ('tfidf', TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=15000)),
            ('clf', LogisticRegression(max_iter=1200, class_weight='balanced'))
        ])
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        accuracy = accuracy_score(y_test, y_pred)
        f1_weighted = f1_score(y_test, y_pred, average='weighted', zero_division=0)

        artifact_dir = os.path.join(django_settings.BASE_DIR, 'static', 'assets', 'ml_artifacts')
        os.makedirs(artifact_dir, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        model_path = os.path.join(artifact_dir, f'issue_{target_field.lower()}_model_{stamp}.pkl')
        metadata_path = os.path.join(artifact_dir, f'issue_{target_field.lower()}_model_{stamp}.json')

        with open(model_path, 'wb') as f:
            pickle.dump(model, f)

        metadata = {
            'target': target_field,
            'trained_at': datetime.now().isoformat(),
            'samples_total': len(texts),
            'samples_used': len(filtered_texts),
            'train_size': len(X_train),
            'test_size': len(X_test),
            'accuracy': round(float(accuracy), 4),
            'f1_weighted': round(float(f1_weighted), 4),
            'class_distribution': dict(Counter(filtered_labels)),
            'features': ['Title', 'Description', 'Location', 'Department']
        }

        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=True, indent=2)

        # Count only successful training runs.
        cache.set(train_count_key, used_today + 1, timeout=60 * 60 * 24)

        if is_page_trigger:
            remaining = max(daily_limit - (used_today + 1), 0)
            return redirect_back(msg=f'Issue ML training completed successfully. Remaining today: {remaining}')

        return JsonResponse(
            {
                'msg': 'Issue ML training completed successfully.',
                'target': target_field,
                'daily_limit': daily_limit,
                'used_today': used_today + 1,
                'metrics': {
                    'accuracy': metadata['accuracy'],
                    'f1_weighted': metadata['f1_weighted']
                },
                'artifacts': {
                    'model_path': model_path,
                    'metadata_path': metadata_path
                }
            }
        )
    except Exception as e:
        if is_page_trigger:
            return redirect_back(err=f'Training failed: {e}')
        return JsonResponse(
            {
                'err': 'Training failed.',
                'detail': str(e)
            },
            status=500
        )


# ---------------------------------------------------------------------------
# AI Review Queue
# ---------------------------------------------------------------------------
def _decode_json_body(request):
    try:
        return json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        return {}


@csrf_exempt
def ai_review_queue(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_ai_review_access(request.session.get('utype')):
        return redirect('main:index')

    sync_ai_review_once_per_session(request)
    op = AIReviewOperation()
    status = (request.GET.get('status') or '').strip() or None
    category = (request.GET.get('category') or '').strip() or None

    try:
        confidence_min = float(request.GET.get('confidence_min')) if request.GET.get('confidence_min') else None
    except Exception:
        confidence_min = None
    try:
        confidence_max = float(request.GET.get('confidence_max')) if request.GET.get('confidence_max') else None
    except Exception:
        confidence_max = None
    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except Exception:
        page = 1
    try:
        page_size = max(min(int(request.GET.get('page_size', 20)), 200), 1)
    except Exception:
        page_size = 20

    queue_result = op.get_queue(
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        category=category,
        status=status,
        page=page,
        page_size=page_size,
    )
    queue = queue_result.get('records', [])
    pagination = queue_result.get('pagination', {})
    stats = op.queue_stats()
    categories = sorted({record.get('predicted_label') for record in queue if record.get('predicted_label')})

    latest_metadata = get_latest_training_metadata()
    return themed_render(
        request,
        'main/ai_review_queue.html',
        {
            'queue': queue,
            'queue_stats': stats,
            'queue_categories': categories,
            'queue_pagination': pagination,
            'current_status': status or '',
            'current_category': category or '',
            'current_confidence_min': confidence_min if confidence_min is not None else '',
            'current_confidence_max': confidence_max if confidence_max is not None else '',
            'current_page': page,
            'current_page_size': page_size,
            'training_metadata': latest_metadata,
        },
    )


@csrf_exempt
def ai_review_queue_api(request):
    if request.method != 'GET':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_ai_review_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    sync_ai_review_once_per_session(request)
    status = (request.GET.get('status') or '').strip() or None
    category = (request.GET.get('category') or '').strip() or None
    try:
        confidence_min = float(request.GET.get('confidence_min')) if request.GET.get('confidence_min') else None
    except Exception:
        confidence_min = None
    try:
        confidence_max = float(request.GET.get('confidence_max')) if request.GET.get('confidence_max') else None
    except Exception:
        confidence_max = None
    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except Exception:
        page = 1
    try:
        page_size = max(min(int(request.GET.get('page_size', 20)), 200), 1)
    except Exception:
        page_size = 20

    op = AIReviewOperation()
    queue_result = op.get_queue(
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        category=category,
        status=status,
        page=page,
        page_size=page_size,
    )
    records = queue_result.get('records', [])
    pagination = queue_result.get('pagination', {})
    categories = sorted({record.get('predicted_label') for record in records if record.get('predicted_label')})
    return JsonResponse({'records': records, 'stats': op.queue_stats(), 'categories': categories, 'pagination': pagination})


@csrf_exempt
def ai_review_approve_api(request):
    if request.method != 'POST':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_ai_review_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    payload = _decode_json_body(request)
    record_id = payload.get('record_id') or request.POST.get('record_id')
    if not record_id:
        return JsonResponse({'err': 'record_id is required.'}, status=400)

    save_to_training = parse_bool(
        payload.get('save_to_training', request.POST.get('save_to_training', True)),
        default=True,
    )
    reviewer = request.session.get('user')
    stat = AIReviewOperation().approve(
        record_id=record_id,
        reviewer=reviewer,
        save_to_training=bool(save_to_training),
    )
    if stat.get('err'):
        return JsonResponse(stat, status=404)
    return JsonResponse(stat)


@csrf_exempt
def ai_review_correct_api(request):
    if request.method != 'POST':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_ai_review_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    payload = _decode_json_body(request)
    record_id = payload.get('record_id') or request.POST.get('record_id')
    corrected_label = payload.get('corrected_label') or request.POST.get('corrected_label')
    corrected_severity = payload.get('corrected_severity') or request.POST.get('corrected_severity')
    save_to_training = parse_bool(
        payload.get('save_to_training', request.POST.get('save_to_training', True)),
        default=True,
    )

    if not record_id or not corrected_label or not corrected_severity:
        return JsonResponse({'err': 'record_id, corrected_label and corrected_severity are required.'}, status=400)

    reviewer = request.session.get('user')
    stat = AIReviewOperation().correct(
        record_id=record_id,
        corrected_label=corrected_label,
        corrected_severity=corrected_severity,
        reviewer=reviewer,
        save_to_training=bool(save_to_training),
    )
    if stat.get('err'):
        return JsonResponse(stat, status=404)
    return JsonResponse(stat)


@csrf_exempt
def ai_review_reject_api(request):
    if request.method != 'POST':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_ai_review_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    payload = _decode_json_body(request)
    record_id = payload.get('record_id') or request.POST.get('record_id')
    reason = payload.get('reason') or request.POST.get('reason') or ''
    if not record_id:
        return JsonResponse({'err': 'record_id is required.'}, status=400)

    reviewer = request.session.get('user')
    stat = AIReviewOperation().reject(record_id=record_id, reviewer=reviewer, reason=reason)
    if stat.get('err'):
        return JsonResponse(stat, status=404)
    return JsonResponse(stat)


@csrf_exempt
def ai_review_export_api(request):
    if request.method != 'GET':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_ai_review_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    rows = AIReviewOperation().export_approved_data()
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="ai_training_dataset_export.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            'record_id',
            'source_issue_id',
            'image',
            'final_label',
            'final_severity',
            'predicted_label',
            'predicted_severity',
            'confidence',
            'reviewed_by',
            'review_action',
            'dataset_version',
            'created_at',
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get('record_id'),
                row.get('source_issue_id'),
                row.get('image'),
                row.get('final_label'),
                row.get('final_severity'),
                row.get('predicted_label'),
                row.get('predicted_severity'),
                row.get('confidence'),
                row.get('reviewed_by'),
                row.get('review_action'),
                row.get('dataset_version'),
                row.get('created_at'),
            ]
        )
    return response



@csrf_exempt
def settings(request):
    if 'user' not in request.session:
        return redirect('main:login')

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_super_admin_access(request.session.get('utype')):
        return redirect('main:index')

    dao = SystemSettingsDAO()
    current = dao.get_current_settings(cache_backend=cache).get('settings', {})
    context = {
        'settings_data': current,
    }
    return themed_render(request, 'main/settings.html', context)


@csrf_exempt
def settings_get_api(request):
    if request.method != 'GET':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_super_admin_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    data = SystemSettingsDAO().get_current_settings(cache_backend=cache)
    return JsonResponse(
        {
            'settings': data.get('settings', {}),
            'cache': {
                'backend': 'redis_or_default',
                'hit': bool(data.get('cached')),
                'key': SystemSettingsDAO.CACHE_KEY,
            },
        }
    )


@csrf_exempt
def settings_update_api(request):
    if request.method != 'POST':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_super_admin_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    payload = {}
    if request.content_type and 'multipart/form-data' in request.content_type:
        try:
            payload = json.loads(request.POST.get('payload', '{}'))
        except Exception:
            payload = {}
    else:
        try:
            payload = json.loads(request.body.decode('utf-8')) if request.body else {}
        except Exception:
            payload = {}

    if not isinstance(payload, dict):
        return JsonResponse({'err': 'Invalid payload.'}, status=400)

    current = SystemSettingsDAO().get_current_settings(cache_backend=cache).get('settings', {})
    candidate = deepcopy(current)
    for section in ['general', 'user_management', 'ai_system', 'notifications', 'festival']:
        if isinstance(payload.get(section), dict):
            candidate.setdefault(section, {}).update(payload.get(section))

    if request.FILES.get('system_logo_file'):
        logo_file = request.FILES['system_logo_file']
        storage = FileSystemStorage(location=django_settings.MEDIA_ROOT, base_url=django_settings.MEDIA_URL)
        ext = os.path.splitext(logo_file.name)[1] or '.png'
        saved_name = storage.save(f"system_settings/logo_{uuid.uuid4().hex}{ext}", logo_file)
        candidate.setdefault('general', {})['system_logo'] = storage.url(saved_name)

    actor = request.session.get('user') or 'System'
    result = SystemSettingsDAO().update_settings(candidate, actor=actor, cache_backend=cache)
    return JsonResponse(result)


@csrf_exempt
def settings_reset_api(request):
    if request.method != 'POST':
        return JsonResponse({'err': 'Method not allowed.'}, status=405)
    if 'user' not in request.session:
        return JsonResponse({'err': 'Unauthorized'}, status=401)

    if not request.session.get('utype'):
        request.session['utype'] = UserOperation().checkType(request.session.get('user'))

    if not has_super_admin_access(request.session.get('utype')):
        return JsonResponse({'err': 'Forbidden'}, status=403)

    actor = request.session.get('user') or 'System'
    result = SystemSettingsDAO().reset_defaults(actor=actor, cache_backend=cache)
    return JsonResponse(result)


@csrf_exempt
def privacy_policy(request):
    if 'user' not in request.session:
        return redirect('main:login')

    return themed_render(request, 'main/privacy_policy.html')


@csrf_exempt
def terms_of_service(request):
    if 'user' not in request.session:
        return redirect('main:login')

    return themed_render(request, 'main/terms_of_service.html')
