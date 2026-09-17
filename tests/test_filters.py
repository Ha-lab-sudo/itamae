import unittest

from app import app, filter_shelters, get_home_instructions


class FilterSheltersTests(unittest.TestCase):
    def test_filters_by_facility_and_district(self):
        shelters = [
            {'name': 'A', 'district': '青森', 'pets': '可', 'wheelchair': '対応', 'toilet': 'あり'},
            {'name': 'B', 'district': '青森', 'pets': '不可', 'wheelchair': '対応', 'toilet': 'あり'},
            {'name': 'C', 'district': '東', 'pets': '可', 'wheelchair': '不可', 'toilet': 'なし'},
        ]

        self.assertEqual(
            [item['name'] for item in filter_shelters('青森', ['pets'], shelters)],
            ['A']
        )
        self.assertEqual(
            [item['name'] for item in filter_shelters(None, ['wheelchair', 'toilet'], shelters)],
            ['A', 'B']
        )


class HomeInstructionsTests(unittest.TestCase):
    def test_filters_and_sorts_resident_instructions_for_home(self):
        records = [
            {'id': 1, 'target': '住民', 'area': '北', 'content': '低い通知', 'urgency': '低', 'status': '発表'},
            {'id': 2, 'target': '住民', 'area': '北', 'content': '高い通知', 'urgency': '高', 'status': '発表'},
            {'id': 3, 'target': '住民', 'area': '南', 'content': '南側通知', 'urgency': '中', 'status': '発表'},
            {'id': 4, 'target': '住民', 'area': '北', 'content': '解除済み', 'urgency': '高', 'status': '解除'},
            {'id': 5, 'target': '防災課', 'area': '北', 'content': '職員向け', 'urgency': '高', 'status': '発表'},
            {'id': 6, 'target': '住民', 'area': '北', 'content': '中通知', 'urgency': '中', 'status': '発表'},
        ]

        self.assertEqual(
            [item['id'] for item in get_home_instructions('北', records)],
            [2, 6, 1]
        )
        self.assertEqual(
            [item['id'] for item in get_home_instructions('南', records)],
            [3]
        )

    def test_rejects_invalid_home_area(self):
        with self.assertRaises(ValueError):
            get_home_instructions('西')


class ShelterSearchPageTests(unittest.TestCase):
    def test_search_form_has_required_area_and_conditions(self):
        with app.test_client() as client:
            response = client.get('/shelter_search')
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('name="area"', html)
            self.assertIn('北側', html)
            self.assertIn('南側', html)
            self.assertIn('name="district"', html)
            self.assertIn('name="pet_ok"', html)
            self.assertIn('name="wheelchair_ok"', html)
            self.assertIn('name="multipurpose_toilet"', html)
            self.assertIn('method="get"', html)
            self.assertIn('action="/search_results"', html)

    def test_search_results_route_accepts_area_parameters(self):
        with app.test_client() as client:
            response = client.get('/search_results?area=%E5%8C%97%E5%81%B4&district=%E9%9D%92%E6%9D%BE&pet_ok=1&wheelchair_ok=1')
            self.assertEqual(response.status_code, 200)
            self.assertIn('北側', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
