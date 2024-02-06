from __future__ import annotations

import datetime
import importlib
import math
import os
import shutil
from pathlib import Path
from subprocess import run
from typing import Any, Optional

from flask import flash, g, render_template, request, url_for
from flask_babel import format_number, lazy_gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm
from werkzeug.exceptions import abort
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
from wtforms import StringField, TextAreaField
from wtforms.validators import InputRequired

from openatlas import app
from openatlas.database.connect import Transaction
from openatlas.display.image_processing import (
    create_resized_images, delete_orphaned_resized_images)
from openatlas.display.tab import Tab
from openatlas.display.table import Table
from openatlas.display.util import (
    button, check_iiif_activation, check_iiif_file_exist,
    convert_image_to_iiif, convert_size,
    display_form, display_info, format_date, get_file_path, is_authorized,
    link, manual, required_group, sanitize, send_mail, uc_first)
from openatlas.forms.field import SubmitField
from openatlas.forms.setting import (
    ApiForm, ContentForm, FilesForm, FrontendForm, GeneralForm, IiifForm,
    LogForm, MailForm, MapForm, ModulesForm, SimilarForm, TestMailForm)
from openatlas.forms.util import get_form_settings, set_form_settings
from openatlas.models.content import get_content, update_content
from openatlas.models.entity import Entity
from openatlas.models.imports import Import
from openatlas.models.link import Link
from openatlas.models.settings import Settings
from openatlas.models.type import Type
from openatlas.models.user import User


@app.route('/admin', methods=['GET', 'POST'], strict_slashes=False)
@required_group('readonly')
def admin_index() -> str:
    users = User.get_all()
    tabs = {
        'files': Tab(
            _('files'),
            render_template(
                'admin/file.html',
                info=get_form_settings(FilesForm()),
                disk_space_info=get_disk_space_info()),
            buttons=[
                manual('entity/file'),
                button(_('edit'), url_for('settings', category='files'))
                if is_authorized('manager') else '',
                button(_('list'), url_for('index', view='file')),
                button(_('file'), url_for('insert', class_='file'))
                if is_authorized('contributor') else '']),
        'user': Tab(
            _('user'),
            table=get_user_table(users),
            buttons=[
                manual('admin/user'),
                button(_('activity'), url_for('user_activity')),
                get_newsletter_button(users),
                button(_('user'), url_for('user_insert'))
                if is_authorized('manager') else ''])}
    if is_authorized('admin'):
        tabs['general'] = Tab(
            'general',
            display_info(get_form_settings(GeneralForm())),
            buttons=[
                manual('admin/general'),
                button(_('edit'), url_for('settings', category='general')),
                button(_('system log'), url_for('log'))])
        tabs['email'] = Tab(
            'email',
            display_info(get_form_settings(MailForm())) + get_test_mail_form(),
            buttons=[
                manual('admin/mail'),
                button(_('edit'), url_for('settings', category='mail'))])
        tabs['IIIF'] = Tab(
            'IIIF',
            display_info(get_form_settings(IiifForm())),
            buttons=[
                manual('admin/iiif'),
                button(_('edit'), url_for('settings', category='iiif')),
                button(
                    _('convert all files') + f' ({count_files_to_convert()})',
                    url_for('admin_convert_iiif_files'))])
    if is_authorized('manager'):
        tabs['modules'] = Tab(
            _('modules'),
            '<h1>' + uc_first(_('defaults for new user')) + '</h1>'
            + display_info(get_form_settings(ModulesForm())),
            buttons=[
                manual('admin/modules'),
                button(_('edit'), url_for('settings', category='modules'))])
        tabs['map'] = Tab(
            'map',
            display_info(get_form_settings(MapForm())),
            buttons=[
                manual('admin/map'),
                button(_('edit'), url_for('settings', category='map'))])
        tabs['content'] = Tab(
            'content',
            get_content_table(),
            buttons=[manual('admin/content')])
        tabs['frontend'] = Tab(
            'frontend',
            display_info(get_form_settings(FrontendForm())),
            buttons=[
                manual('admin/frontend'),
                button(_('edit'), url_for('settings', category='frontend'))])
    if is_authorized('contributor'):
        tabs['data'] = Tab(
            'data',
            render_template(
                'admin/data.html',
                imports=Import.get_all_projects(),
                info=get_form_settings(ApiForm())))
    return render_template(
        'tabs.html',
        tabs=tabs,
        title=_('admin'),
        crumbs=[_('admin')])


def get_content_table() -> str:
    table = Table(['name'] + list(app.config['LANGUAGES']))
    for item, languages in get_content().items():
        content = [_(item)]
        for language in app.config['LANGUAGES']:
            content.append(sanitize(languages[language], 'text'))
        content.append(link(_('edit'), url_for('admin_content', item=item)))
        table.rows.append(content)
    return table.display()


def get_test_mail_form() -> str:
    if not g.settings['mail']:
        return ''
    form = TestMailForm()
    if form.validate_on_submit():
        subject = _(
            'Test mail from %(site_name)s',
            site_name=g.settings['site_name'])
        body = (_(
            'This test mail was sent by %(username)s',
            username=current_user.username) +
            ' ' + _('at') + ' ' + request.headers['Host'])
        if send_mail(subject, body, form.receiver.data):
            flash(_(
                'A test mail was sent to %(email)s.',
                email=form.receiver.data), 'info')
    elif request.method == 'GET':
        form.receiver.data = current_user.email
    return display_form(form)


def get_newsletter_button(users: list[User]) -> str:
    if g.settings['mail'] and is_authorized('manager'):
        for user in users:
            if user.settings['newsletter']:
                return button(_('newsletter'), url_for('newsletter'))
    return ''


def get_user_table(users: list[User]) -> Table:
    table = Table([
        'username', 'name', 'group', 'email', 'newsletter', 'created',
        'last login', 'entities'],
        defs=[{'className': 'dt-body-right', 'targets': 7}])
    if is_authorized('manager'):
        table.header.append(_('info'))
    for user in users:
        user_entities = ''
        if count := User.get_created_entities_count(user.id):
            user_entities = link(
                format_number(count),
                url_for("user_entities", id_=user.id))
        row = [
            link(user),
            user.real_name,
            user.group,
            user.email if is_authorized('manager')
            or user.settings['show_email'] else '',
            _('yes') if user.settings['newsletter'] else '',
            format_date(user.created),
            format_date(user.login_last_success),
            user_entities]
        if is_authorized('editor'):
            row.append(user.description)
        table.rows.append(row)
    return table


@app.route('/logo/remove')
@required_group('manager')
def logo_remove() -> Response:
    Settings.set_logo()
    return redirect(f"{url_for('admin_index')}#tab-file")


@app.route('/admin/content/<string:item>', methods=['GET', 'POST'])
@required_group('manager')
def admin_content(item: str) -> str | Response:
    for language in app.config['LANGUAGES']:
        setattr(
            ContentForm,
            language,
            TextAreaField(render_kw={'class': 'tinymce'}))
    setattr(ContentForm, 'save', SubmitField(_('save')))
    form = ContentForm()
    if form.validate_on_submit():
        data = []
        for language in app.config['LANGUAGES']:
            data.append({
                'name': item,
                'language': language,
                'text': getattr(form, language).data or ''})
        update_content(data)
        flash(_('info update'), 'info')
        return redirect(f"{url_for('admin_index')}#tab-content")
    for language in app.config['LANGUAGES']:
        getattr(form, language).data = get_content()[item][language]
    return render_template(
        'tabs.html',
        tabs={'content': Tab('content', form=form)},
        title=_('content'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-content"],
            _(item)])


@app.route('/check_links')
@required_group('contributor')
def check_links() -> str:
    tab = Tab(
        'check_links',
        table=Table(
            ['domain', 'property', 'range'],
            [[x['domain'], x['property'], x['range']]
             for x in Link.get_invalid_cidoc_links()]),
        buttons=[manual('admin/data_integrity_checks')])
    tab.content = _('Congratulations, everything looks fine!') \
        if not tab.table.rows else None
    return render_template(
        'tabs.html',
        tabs={'check_links': tab},
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-data"],
            _('check links')])


@app.route('/check_link_duplicates')
@app.route('/check_link_duplicates/<delete>')
@required_group('contributor')
def check_link_duplicates(delete: Optional[str] = None) -> str | Response:
    if delete:
        count = Link.delete_link_duplicates()
        g.logger.log('info', 'admin', f"Deleted duplicate links: {count}")
        flash(f"{_('deleted links')}: {count}", 'info')
        return redirect(url_for('check_link_duplicates'))
    tab = Tab(
        'check_link_duplicates',
        buttons=[manual('admin/data_integrity_checks')])
    tab.table = Table([
        'domain', 'range', 'property_code', 'description', 'type_id',
        'begin_from', 'begin_to', 'begin_comment', 'end_from', 'end_to',
        'end_comment', 'count'])
    for row in Link.check_link_duplicates():
        tab.table.rows.append([
            link(Entity.get_by_id(row['domain_id'])),
            link(Entity.get_by_id(row['range_id'])),
            link(g.properties[row['property_code']]),
            row['description'],
            link(g.types[row['type_id']]) if row['type_id'] else '',
            format_date(row['begin_from']),
            format_date(row['begin_to']),
            row['begin_comment'],
            format_date(row['end_from']),
            format_date(row['end_to']),
            row['end_comment'],
            row['count']])
    if tab.table.rows:
        tab.buttons.append(
            button(
                _('delete link duplicates'),
                url_for('check_link_duplicates', delete='delete')))
    else:  # Check single types for multiple use
        tab.table = Table(
            ['entity', 'class', 'base type', 'incorrect multiple types'])
        for row in Link.check_single_type_duplicates():
            remove_links = []
            for type_ in row['offending_types']:
                url = url_for(
                    'delete_single_type_duplicate',
                    entity_id=row['entity'].id,
                    type_id=type_.id)
                remove_links.append(
                    f'<a href="{url}" class="uc-first">' + _("remove") + '</a>'
                    f' {type_.name}')
            tab.table.rows.append([
                link(row['entity']),
                row['entity'].class_.label,
                link(g.types[row['type'].id]),
                '<br><br>'.join(remove_links)])
    if not tab.table.rows:
        tab.content = _('Congratulations, everything looks fine!')
    return render_template(
        'tabs.html',
        tabs={'tab': tab},
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-data"],
            _('check link duplicates')])


@app.route('/delete_single_type_duplicate/<int:entity_id>/<int:type_id>')
@required_group('contributor')
def delete_single_type_duplicate(entity_id: int, type_id: int) -> Response:
    g.types[type_id].remove_entity_links(entity_id)
    flash(_('link removed'), 'info')
    return redirect(url_for('check_link_duplicates'))


@app.route('/settings/<category>', methods=['GET', 'POST'])
@required_group('manager')
def settings(category: str) -> str | Response:
    if category in ['general', 'mail', 'iiif'] and not is_authorized('admin'):
        abort(403)
    form = getattr(
        importlib.import_module('openatlas.forms.setting'),
        f"{uc_first(category)}Form")()
    tab = category \
        .replace('api', 'data') \
        .replace('mail', 'email') \
        .replace('iiif', 'IIIF')
    if form.validate_on_submit():
        data = {}
        for field in form:
            if field.type in ['CSRFTokenField', 'HiddenField', 'SubmitField']:
                continue
            value = field.data
            if field.type == 'FieldList':
                value = ' '.join(set(filter(None, field.data)))
            if field.type == 'BooleanField':
                value = 'True' if field.data else ''
            if isinstance(value, str):
                value = value.strip()
            data[field.name] = value
        Transaction.begin()
        try:
            Settings.update(data)
            g.logger.log('info', 'settings', 'Settings updated')
            Transaction.commit()
            flash(_('info update'), 'info')
        except Exception as e:  # pragma: no cover
            Transaction.rollback()
            g.logger.log('error', 'database', 'transaction failed', e)
            flash(_('error transaction'), 'error')
        return redirect(f"{url_for('admin_index')}#tab-{tab}")
    set_form_settings(form)
    return render_template(
        'content.html',
        content=display_form(form, manual_page=f"admin/{category}"),
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-{tab}"],
            _(category)])


@app.route('/check_similar', methods=['GET', 'POST'])
@required_group('contributor')
def check_similar() -> str:
    form = SimilarForm()
    form.classes.choices = [
        (class_.name, class_.label)
        for name, class_ in g.classes.items() if class_.label and class_.view]
    table = None
    if form.validate_on_submit():
        table = Table(['name', _('count')])
        for sample in Entity.get_similar_named(
                form.classes.data,
                form.ratio.data).values():
            similar = [link(entity) for entity in sample['entities']]
            table.rows.append([
                f"{link(sample['entity'])}<br><br>{'<br><br>'.join(similar)}",
                len(sample['entities']) + 1])
    content = display_form(form, manual_page='admin/data_integrity_checks')
    content += ('<p class="uc-first">' + _('no entries') + '</p>') \
        if table and not table.rows else ''
    return render_template(
        'tabs.html',
        tabs={'similar': Tab('similar', content, table=table)},
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-data"],
            _('check similar names')])


@app.route('/check/dates')
@required_group('contributor')
def check_dates() -> str:
    tabs = {
        'dates': Tab(
            'invalid_dates',
            table=Table([
                'name',
                'class',
                'type',
                'created',
                'updated',
                'description'])),
        'link_dates': Tab(
            'invalid_link_dates',
            table=Table(['link', 'domain', 'range'])),
        'involvement_dates': Tab(
            'invalid_involvement_dates',
            table=Table(
                ['actor', 'event', 'class', 'involvement', 'description']))}
    for entity in Entity.get_invalid_dates():
        tabs['dates'].table.rows.append([
            link(entity),
            entity.class_.label,
            link(entity.standard_type),
            format_date(entity.created),
            format_date(entity.modified),
            entity.description])
    for item in Link.get_invalid_link_dates():
        tabs['link_dates'].table.rows.append([
            link(
                item.property.name,
                url_for('link_update', id_=item.id, origin_id=item.domain.id)),
            link(item.domain),
            link(item.range)])
    for link_ in Link.invalid_involvement_dates():
        event = link_.domain
        actor = link_.range
        data = [
            link(actor),
            link(event),
            event.class_.label,
            link_.type.name if link_.type else '',
            link_.description,
            link(
                _('edit'),
                url_for('link_update', id_=link_.id, origin_id=actor.id))]
        tabs['involvement_dates'].table.rows.append(data)
    for tab in tabs.values():
        tab.buttons = [manual('admin/data_integrity_checks')]
        if not tab.table.rows:
            tab.content = _('Congratulations, everything looks fine!')
    return render_template(
        'tabs.html',
        tabs=tabs,
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-data"],
            _('check dates')])


@app.route('/orphans')
@required_group('contributor')
def orphans() -> str:
    header = [
        'name',
        'class',
        'type',
        'system type',
        'created',
        'updated',
        'description']
    tabs = {
        'orphans': Tab('orphans', table=Table(header)),
        'unlinked': Tab('unlinked', table=Table(header)),
        'types': Tab(
            'type',
            table=Table(
                ['name', 'root'],
                [[link(type_), link(g.types[type_.root[0]])]
                    for type_ in Type.get_type_orphans()])),
        'missing_files': Tab('missing_files', table=Table(header)),
        'orphaned_files': Tab(
            'orphaned_files',
            table=Table(['name', 'size', 'date', 'ext'])),
        'orphaned_iiif_files': Tab(
            'orphaned_iiif_files',
            table=Table(['name', 'size', 'date', 'ext'])),
        'orphaned_subunits': Tab(
            'orphaned_subunits',
            table=Table([
                'id', 'name', 'class', 'created', 'modified', 'description'])),
        'circular': Tab('circular_dependencies', table=Table(
            ['entity'],
            [[link(e)] for e in Entity.get_entities_linked_to_itself()]))}

    for entity in Entity.get_orphans():
        tabs[
            'unlinked'
            if entity.class_.view else 'orphans'].table.rows.append([
                link(entity),
                link(entity.class_),
                link(entity.standard_type),
                entity.class_.label,
                format_date(entity.created),
                format_date(entity.modified),
                entity.description])

    # Orphaned file entities with no corresponding file
    entity_file_ids = []
    for entity in Entity.get_by_class('file', types=True):
        entity_file_ids.append(entity.id)
        if not get_file_path(entity):
            tabs['missing_files'].table.rows.append([
                link(entity),
                link(entity.class_),
                link(entity.standard_type),
                entity.class_.label,
                format_date(entity.created),
                format_date(entity.modified),
                entity.description])

    # Orphaned files with no corresponding entity
    for file in app.config['UPLOAD_PATH'].iterdir():
        if file.name != '.gitignore' \
                and os.path.isfile(file) \
                and file.stem.isdigit() \
                and int(file.stem) not in entity_file_ids:
            confirm = _('Delete %(name)s?', name=file.name.replace("'", ''))
            tabs['orphaned_files'].table.rows.append([
                file.stem,
                convert_size(file.stat().st_size),
                format_date(
                    datetime.datetime.utcfromtimestamp(file.stat().st_ctime)),
                file.suffix,
                link(_('download'), url_for('download', filename=file.name)),
                link(
                    _('delete'),
                    url_for('admin_file_delete', filename=file.name),
                    js=f"return confirm('{confirm}')")
                if is_authorized('editor') else ''])

    # Orphaned IIIF files with no corresponding entity
    if g.settings['iiif'] and g.settings['iiif_path']:
        for file in Path(g.settings['iiif_path']).iterdir():
            confirm = _('Delete %(name)s?', name=file.name.replace("'", ''))
            if file.name != '.gitignore' \
                    and os.path.isfile(file) \
                    and file.stem.isdigit() \
                    and int(file.stem) not in entity_file_ids:
                tabs['orphaned_iiif_files'].table.rows.append([
                    file.stem,
                    convert_size(file.stat().st_size),
                    format_date(
                        datetime.datetime.utcfromtimestamp(
                            file.stat().st_ctime)),
                    file.suffix,
                    link(
                        _('delete'),
                        url_for('admin_file_iiif_delete', filename=file.name),
                        js=f"return confirm('{confirm}')")
                    if is_authorized('editor') else ''])

    # Orphaned subunits (without connection to a P46 super)
    for entity in Entity.get_orphaned_subunits():
        tabs['orphaned_subunits'].table.rows.append([
            entity.id,
            entity.name,
            entity.class_.label,
            format_date(entity.created),
            format_date(entity.modified),
            entity.description])

    for tab in tabs.values():
        tab.buttons = [manual('admin/data_integrity_checks')]
        if not tab.table.rows:
            tab.content = _('Congratulations, everything looks fine!')

    if tabs['orphaned_files'].table.rows and is_authorized('admin'):
        text = _('delete all files without corresponding entities?')
        tabs['orphaned_files'].buttons.append(
            button(
                _('delete all files'),
                url_for('admin_file_delete', filename='all'),
                onclick=f"return confirm('{text}')"))
    return render_template(
        'tabs.html',
        tabs=tabs,
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-data"],
            _('orphans')])


@app.route('/admin/file/delete/<filename>')
@required_group('editor')
def admin_file_delete(filename: str) -> Response:
    if filename != 'all':  # Delete one file
        try:
            (app.config['UPLOAD_PATH'] / filename).unlink()
            flash(f"{filename} {_('was deleted')}", 'info')
        except Exception as e:
            g.logger.log('error', 'file', f'deletion of {filename} failed', e)
            flash(_('error file delete'), 'error')
        return redirect(f"{url_for('orphans')}#tab-orphaned-files")

    # Delete all files with no corresponding entity
    if is_authorized('admin'):  # pragma: no cover - don't test, ever
        entity_file_ids = [entity.id for entity in Entity.get_by_class('file')]
        for f in app.config['UPLOAD_PATH'].iterdir():
            if f.name != '.gitignore' and int(f.stem) not in entity_file_ids:
                try:
                    (app.config['UPLOAD_PATH'] / f.name).unlink()
                except Exception as e:
                    g.logger.log(
                        'error', 'file', f'deletion of {f.name} failed', e)
                    flash(_('error file delete'), 'error')
    return redirect(
        f"{url_for('orphans')}#tab-orphaned-files")  # pragma: no cover


@app.route('/admin/file/iiif/delete/<filename>')
@required_group('editor')
def admin_file_iiif_delete(filename: str) -> Response:
    try:
        (Path(g.settings['iiif_path']) / filename).unlink()
        flash(f"{filename} {_('was deleted')}", 'info')
    except Exception as e:
        g.logger.log('error', 'file', f'deletion of IIIF {filename} failed', e)
        flash(_('error file delete'), 'error')
    return redirect(f"{url_for('orphans')}#tab-orphaned-iiif-files")


@app.route('/admin/logo/')
@app.route('/admin/logo/<int:id_>')
@required_group('manager')
def admin_logo(id_: Optional[int] = None) -> str | Response:
    if g.settings['logo_file_id']:
        abort(418)  # pragma: no cover - logo already set
    if id_:
        Settings.set_logo(id_)
        return redirect(f"{url_for('admin_index')}#tab-file")
    table = Table([''] + g.table_headers['file'] + ['date'])
    for entity in Entity.get_display_files():
        date = 'N/A'
        if entity.id in g.files:
            date = format_date(
                datetime.datetime.utcfromtimestamp(
                    g.files[entity.id].stat().st_ctime))
        table.rows.append([
            link(_('set'), url_for('admin_logo', id_=entity.id)),
            entity.name,
            link(entity.standard_type),
            entity.get_file_size(),
            entity.get_file_ext(),
            entity.description,
            date])
    return render_template(
        'tabs.html',
        tabs={'logo': Tab('files', table=table)},
        title=_('logo'),
        crumbs=[[
            _('admin'),
            f"{url_for('admin_index')}#tab-files"],
            _('logo')])


@app.route('/log', methods=['GET', 'POST'])
@required_group('admin')
def log() -> str:
    form = LogForm()
    form.user.choices = [(0, _('all'))] + User.get_users_for_form()
    table = Table(
        ['date', 'priority', 'type', 'message', 'user', 'info'],
        order=[[0, 'desc']])
    logs = g.logger.get_system_logs(
        form.limit.data,
        form.priority.data,
        form.user.data)
    for row in logs:
        user = None
        if row['user_id']:
            user = f"user id: {row['user_id']}"
            if user_ := User.get_by_id(row['user_id']):
                user = link(user_)
        table.rows.append([
            row['created'].replace(microsecond=0).isoformat()
            if row['created'] else '',
            f"{row['priority']} {app.config['LOG_LEVELS'][row['priority']]}",
            row['type'],
            row['message'],
            user,
            row['info']])
    buttons = [button(
        _('delete all logs'),
        url_for('log_delete'),
        onclick=f"return confirm('{_('delete all logs')}?')")]

    return render_template(
        'tabs.html',
        tabs={'log': Tab('log', form=form, table=table, buttons=buttons)},
        title=_('admin'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-general"],
            _('system log')])


@app.route('/log/delete')
@required_group('admin')
def log_delete() -> Response:
    g.logger.delete_all_system_logs()
    flash(_('Logs deleted'), 'info')
    return redirect(url_for('log'))


@app.route('/newsletter', methods=['GET', 'POST'])
@required_group('manager')
def newsletter() -> str | Response:
    class NewsLetterForm(FlaskForm):
        subject = StringField(
            '',
            [InputRequired()],
            render_kw={
                'class': 'w-100',
                'placeholder': uc_first(_('subject')),
                'autofocus': True})
        body = TextAreaField(
            '',
            [InputRequired()],
            render_kw={
                'class': 'w-100',
                'rows': '8',
                'placeholder': uc_first(_('content'))})
        save = SubmitField(uc_first(_('send')))

    form = NewsLetterForm()
    if form.validate_on_submit():
        count = 0
        for user_id in request.form.getlist('recipient'):
            user = User.get_by_id(int(user_id))
            if user \
                    and user.settings['newsletter'] \
                    and user.active \
                    and user.email:
                code = User.generate_password()
                user.unsubscribe_code = code
                user.update()
                link_ = f"{request.scheme}://{request.headers['Host']}"
                link_ += url_for('index_unsubscribe', code=code)
                if send_mail(
                        form.subject.data,
                        f'{form.body.data}\n\n'
                        f'{_("To unsubscribe use the link below.")}\n\n'
                        f'{link_}',
                        user.email):
                    count += 1
        flash(f"{_('Newsletter send')}: {count}", 'info')
        return redirect(url_for('admin_index'))
    table = Table(['username', 'email', 'receiver'])
    for user in User.get_all():
        if user and user.settings['newsletter'] and user.active:
            table.rows.append([
                user.username,
                user.email,
                f'<input value="{user.id}" name="recipient" type="checkbox" '
                f'checked="checked">'])
    return render_template(
        'admin/newsletter.html',
        form=form,
        table=table,
        title=_('newsletter'),
        crumbs=[
            [_('admin'), f"{url_for('admin_index')}#tab-user"],
            _('newsletter')])


@app.route('/resize_images')
@required_group('admin')
def resize_images() -> Response:
    create_resized_images()
    flash(_('images were created'), 'info')
    return redirect(url_for('admin_index') + '#tab-data')


@app.route('/admin/delete_orphaned_resized_images')
@required_group('admin')
def admin_delete_orphaned_resized_images() -> Response:
    delete_orphaned_resized_images()
    flash(_('resized orphaned images were deleted'), 'info')
    return redirect(url_for('admin_index') + '#tab-data')


@app.route('/admin/convert_iiif_files')
@required_group('admin')
def admin_convert_iiif_files() -> Response:
    convert_iiif_files()
    return redirect(url_for('admin_index') + '#tab-IIIF')


def get_disk_space_info() -> Optional[dict[str, Any]]:
    if os.name == 'posix':
        process = run(
            ['du', '-sb', app.config['FILES_PATH']],
            capture_output=True,
            text=True,
            check=True)
        files_size = int(process.stdout.split()[0])
    else:
        files_size = 40999999999  # pragma: no cover
    stats = shutil.disk_usage(app.config['UPLOAD_PATH'])
    percent_free = 100 - math.ceil(stats.free / (stats.total / 100))
    percent_files = math.ceil(files_size / (stats.total / 100))
    other_files = stats.total - stats.free - files_size
    return {
        'total': convert_size(stats.total),
        'project': convert_size(files_size),
        'other_files': convert_size(other_files),
        'free': convert_size(stats.free),
        'percent_used': percent_free,
        'percent_project': percent_files,
        'percent_other': 100 - (percent_files + percent_free)}


def count_files_to_convert() -> int:
    total_files = 0
    converted_files = 0
    existing_files = [entity.id for entity in Entity.get_by_class('file')]
    for file_id, file_path in g.files.items():
        if (file_id in existing_files and
                file_path.suffix in g.display_file_ext):
            total_files += 1
            if check_iiif_file_exist(file_id):
                converted_files += 1

    return total_files - converted_files


def convert_iiif_files() -> None:
    if not check_iiif_activation():  # pragma: no cover
        flash(_('please activate IIIF'), 'info')
        return
    if not g.settings['iiif_conversion']:  # pragma: no cover
        flash(_('please activate IIIF conversion'), 'info')
        return
    existing_files = [entity.id for entity in Entity.get_by_class('file')]
    for id_, file_path in g.files.items():
        if check_iiif_file_exist(id_):
            continue
        if id_ in existing_files and file_path.suffix in g.display_file_ext:
            convert_image_to_iiif(id_)
    flash(_('all image files are converted'), 'info')
