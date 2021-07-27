import os
import shutil
import subprocess

from flask import g, request
from flask_login import current_user
from flask_wtf import FlaskForm

from openatlas import app
from openatlas.models.date import current_date_for_filename


class Export:

    @staticmethod
    def export_csv(form: FlaskForm) -> None:
        import pandas.io.sql as psql
        date_string = current_date_for_filename()
        path = app.config['EXPORT_DIR'] / 'csv'
        if form.zip.data:
            path = app.config['TMP_DIR'] / \
                   (date_string + '_openatlas_csv_export')
            if path.is_dir():
                shutil.rmtree(path)  # pragma: no cover
            path.mkdir()
        tables = {
            'model_class': ['id', 'name', 'code'],
            'model_class_inheritance': ['id', 'super_code', 'sub_code'],
            'model_entity': [
                'id',
                'name',
                'description',
                'class_code',
                "replace(to_char(begin_from, 'yyyy-mm-dd BC'), ' AD', '')",
                "replace(to_char(begin_to, 'yyyy-mm-dd BC'), ' AD', '')",
                'begin_comment',
                "replace(to_char(end_from, 'yyyy-mm-dd BC'), ' AD', '')",
                "replace(to_char(end_to, 'yyyy-mm-dd BC'), ' AD', '')",
                'end_comment'],
            'model_link': [
                'id',
                'property_code',
                'domain_id',
                'range_id',
                'type_id',
                'description',
                "replace(to_char(begin_from, 'yyyy-mm-dd BC'), ' AD', '')",
                "replace(to_char(begin_to, 'yyyy-mm-dd BC'), ' AD', '')",
                'begin_comment',
                "replace(to_char(end_from, 'yyyy-mm-dd BC'), ' AD', '')",
                "replace(to_char(end_to, 'yyyy-mm-dd BC'), ' AD', '')",
                'end_comment'],
            'model_property': [
                'id', 'code', 'range_class_code', 'domain_class_code', 'name',
                'name_inverse'],
            'model_property_inheritance': ['id', 'super_code', 'sub_code'],
            'gis_point': ['id', 'entity_id', 'name', 'description', 'type'],
            'gis_linestring':
                ['id', 'entity_id', 'name', 'description', 'type'],
            'gis_polygon': ['id', 'entity_id', 'name', 'description', 'type']}
        gis_tables = ['gis_point', 'gis_linestring', 'gis_polygon']
        for table, fields in tables.items():
            if getattr(form, table).data:
                if form.timestamps.data:
                    fields.append('created')
                    fields.append('modified')
                if table in gis_tables:
                    if form.gis_format.data == 'wkt':
                        fields.append("ST_AsText(geom)")
                    elif form.gis_format.data == 'coordinates':
                        if table == 'gis_point':
                            fields.append(
                                "ST_X(geom) || ' ' || "
                                "ST_Y(geom) AS coordinates")
                        else:
                            fields.append("""
                                ST_X(public.ST_PointOnSurface(geom)) || ' ' ||
                                ST_Y(public.ST_PointOnSurface(geom)) 
                                AS polygon_center_point""")
                    else:
                        fields.append('geom')
                data_frame = psql.read_sql(
                    f"SELECT {','.join(fields)} "
                    f"FROM {table.replace('_', '.', 1)};",
                    g.db)
                data_frame.to_csv(
                    path / f'{date_string}_{table}.csv',
                    index=False)
        if form.zip.data:
            info = f"CSV export from: {request.headers['Host']}\n"
            info += \
                f"Created: {date_string} by {current_user.username}\n" \
                f"OpenAtlas version: {app.config['VERSION']}"
            with open(path / 'info.txt', "w") as file:
                print(info, file=file)
            zip_file = app.config['EXPORT_DIR'] / 'csv' / (date_string + '_csv')
            shutil.make_archive(zip_file, 'zip', path)
            shutil.rmtree(path)

    @staticmethod
    def export_sql() -> bool:
        file = app.config['EXPORT_DIR'] / 'sql' \
               / (current_date_for_filename() + '_dump.sql')
        if os.name == 'posix':
            command = \
                f"pg_dump " \
                f"-h {app.config['DATABASE_HOST']} " \
                f"-d {app.config['DATABASE_NAME']} " \
                f"-U {app.config['DATABASE_USER']} " \
                f"-p {app.config['DATABASE_PORT']} " \
                f"-f {file}"
            try:
                subprocess.Popen(
                    command,
                    shell=True,
                    stdin=subprocess.PIPE,
                    env={'PGPASSWORD': app.config['DATABASE_PASS']}).wait()
                with open(os.devnull, 'w') as null:
                    subprocess.Popen(
                        ['7z', 'a', f'{file}.7z', file], stdout=null).wait()
                file.unlink()
            except Exception:  # pragma: no cover
                return False
        else:  # pragma: no cover
            os.popen(
                f'"{shutil.which("pg_dump")}" '
                f'-h 127.0.0.1 '
                f'-d {app.config["DATABASE_NAME"]} '
                f'-U {app.config["DATABASE_USER"]} '
                f'-p {app.config["DATABASE_PORT"]} '
                f'> {file}')
        return True
