import json
import unittest
from unittest.mock import patch

from post_bili import finalize_collection as collection


class CollectionGroupingTests(unittest.TestCase):
    def row(self, disabled):
        return {'season': {'id': 123, 'title': '现场', 'cover': 'existing-cover',
                           'desc': 'existing-description', 'no_section': disabled},
                'sections': {'sections': [{'id': 456, 'title': '正片'}]}}

    def test_new_collection_enables_groups_and_preserves_metadata(self):
        disabled, enabled = self.row(1), self.row(0)
        with patch.object(collection, 'season', side_effect=[json.dumps([disabled]), json.dumps([enabled])]), \
                patch.object(collection, 'season_edit') as edit:
            self.assertEqual(collection.grouped_season(123), enabled)
        edit.assert_called_once_with('edit', {
            'season': enabled['season'], 'sorts': [{'id': 456, 'sort': 1}]})

    def test_existing_groups_are_reused(self):
        enabled = self.row(0)
        with patch.object(collection, 'season', return_value=json.dumps([enabled])), \
                patch.object(collection, 'season_edit') as edit:
            self.assertEqual(collection.grouped_season(123), enabled)
        edit.assert_not_called()

    def test_platform_must_confirm_group_setting(self):
        with patch.object(collection, 'season', return_value=json.dumps([self.row(1)])), \
                patch.object(collection, 'season_edit'), self.assertRaisesRegex(ValueError, '尚未启用'):
            collection.grouped_season(123)
