"""Cursor / Keyset Pagination for high-volume list views in the admin panel.

Avoids slow OFFSET / COUNT(*) queries on tables with tens of thousands of rows
(seats, rooms, students, audit logs).
"""
import base64
import json


class CursorPage:
    def __init__(self, object_list, has_next=False, has_previous=False, next_cursor=None, prev_cursor=None):
        self.object_list = object_list
        self.has_next = has_next
        self.has_previous = has_previous
        self.next_cursor = next_cursor
        self.prev_cursor = prev_cursor

    def __iter__(self):
        return iter(self.object_list)

    def __len__(self):
        return len(self.object_list)


class CursorPaginator:
    """Keyset-based cursor paginator.

    Encodes direction and boundary PKs so Next/Prev links query by
    ``pk < boundary`` (descending) or ``pk > boundary`` (ascending).
    """

    def __init__(self, queryset, page_size=25, order_field='pk', reverse=True):
        self.queryset = queryset
        self.page_size = page_size
        self.order_field = order_field
        self.reverse = reverse

    def encode_cursor(self, pk, direction):
        data = {'p': str(pk), 'd': direction}
        return base64.urlsafe_b64encode(json.dumps(data).encode('utf-8')).decode('ascii')

    def decode_cursor(self, cursor_str):
        if not cursor_str:
            return None
        try:
            raw = base64.urlsafe_b64decode(cursor_str.encode('ascii')).decode('utf-8')
            data = json.loads(raw)
            if 'p' in data and data.get('d') in ('next', 'prev'):
                return data
        except Exception:
            return None
        return None

    def page(self, cursor_str=None):
        cursor = self.decode_cursor(cursor_str)
        qs = self.queryset

        # Cast pk to int if order_field is numeric (e.g. id, pk)
        is_numeric = self.order_field in ('id', 'pk')

        if cursor is None:
            order = f'-{self.order_field}' if self.reverse else self.order_field
            items = list(qs.order_by(order)[:self.page_size + 1])
            has_next = len(items) > self.page_size
            items = items[:self.page_size]
            next_cur = self.encode_cursor(getattr(items[-1], self.order_field), 'next') if (has_next and items) else None
            return CursorPage(items, has_next=has_next, has_previous=False, next_cursor=next_cur, prev_cursor=None)

        raw_pk = cursor['p']
        pk_val = int(raw_pk) if is_numeric and raw_pk.isdigit() else raw_pk
        direction = cursor['d']

        if self.reverse:
            if direction == 'next':
                items = list(qs.filter(**{f'{self.order_field}__lt': pk_val}).order_by(f'-{self.order_field}')[:self.page_size + 1])
                has_next = len(items) > self.page_size
                items = items[:self.page_size]
                next_cur = self.encode_cursor(getattr(items[-1], self.order_field), 'next') if (has_next and items) else None
                prev_cur = self.encode_cursor(getattr(items[0], self.order_field), 'prev') if items else None
                return CursorPage(items, has_next=has_next, has_previous=True, next_cursor=next_cur, prev_cursor=prev_cur)
            else:  # prev
                items = list(qs.filter(**{f'{self.order_field}__gt': pk_val}).order_by(self.order_field)[:self.page_size + 1])
                has_prev = len(items) > self.page_size
                items = items[:self.page_size]
                items.reverse()
                next_cur = self.encode_cursor(getattr(items[-1], self.order_field), 'next') if items else None
                prev_cur = self.encode_cursor(getattr(items[0], self.order_field), 'prev') if (has_prev and items) else None
                return CursorPage(items, has_next=True, has_previous=has_prev, next_cursor=next_cur, prev_cursor=prev_cur)
        else:
            if direction == 'next':
                items = list(qs.filter(**{f'{self.order_field}__gt': pk_val}).order_by(self.order_field)[:self.page_size + 1])
                has_next = len(items) > self.page_size
                items = items[:self.page_size]
                next_cur = self.encode_cursor(getattr(items[-1], self.order_field), 'next') if (has_next and items) else None
                prev_cur = self.encode_cursor(getattr(items[0], self.order_field), 'prev') if items else None
                return CursorPage(items, has_next=has_next, has_previous=True, next_cursor=next_cur, prev_cursor=prev_cur)
            else:  # prev
                items = list(qs.filter(**{f'{self.order_field}__lt': pk_val}).order_by(f'-{self.order_field}')[:self.page_size + 1])
                has_prev = len(items) > self.page_size
                items = items[:self.page_size]
                items.reverse()
                next_cur = self.encode_cursor(getattr(items[-1], self.order_field), 'next') if items else None
                prev_cur = self.encode_cursor(getattr(items[0], self.order_field), 'prev') if (has_prev and items) else None
                return CursorPage(items, has_next=True, has_previous=has_prev, next_cursor=next_cur, prev_cursor=prev_cur)
