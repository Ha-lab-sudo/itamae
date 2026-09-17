import unittest
from unittest.mock import patch

import app as app_module


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_home_and_protected_routes(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        response = self.client.get('/board')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_home_instructions_default_is_all_regions(self):
        response = self.client.get('/api/home_instructions?area=')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['area'], '')

    def test_login_and_shelter_registration(self):
        response = self.client.post('/login', data={'password': '123'})
        self.assertEqual(response.status_code, 302)
        original_shelters = list(app_module.shelters)
        try:
            with patch.object(app_module, 'save_shelters'), patch.object(
                app_module, 'geocode_address', return_value=None
            ):
                response = self.client.post('/shelter_register', data={
                    'name': 'テスト避難所',
                    'area': '北側',
                    'address': '青森市テスト町1-1',
                    'contact': '017-000-0000',
                    'response_conditions': ['ペット同伴可'],
                    'congestion': '空きあり',
                    'opening_status': '受け入れ可',
                })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(app_module.shelters[-1]['address'], '青森市テスト町1-1')
            self.assertEqual(app_module.shelters[-1]['contact'], '017-000-0000')
            self.assertNotIn('周辺の建物', response.get_data(as_text=True))
        finally:
            app_module.shelters[:] = original_shelters

    def test_shelter_registration_stores_map_coordinates(self):
        self.client.post('/login', data={'password': '123'})
        original_shelters = list(app_module.shelters)
        try:
            with patch.object(app_module, 'save_shelters'), patch.object(
                app_module, 'geocode_address', return_value=(40.8244, 140.74)
            ):
                response = self.client.post('/shelter_register', data={
                    'name': '座標テスト避難所',
                    'area': '北側',
                    'postal_code': '030-0801',
                    'address': '青森県青森市新町',
                    'congestion': '空きあり',
                    'opening_status': '受け入れ可',
                })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(app_module.shelters[-1]['postal_code'], '030-0801')
            self.assertEqual(app_module.shelters[-1]['latitude'], 40.8244)
            self.assertEqual(app_module.shelters[-1]['longitude'], 140.74)
        finally:
            app_module.shelters[:] = original_shelters

    def test_shelters_api_and_weather_failure(self):
        response = self.client.get('/shelters')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.get_json(), list)
        with patch('app.urllib.request.urlopen', side_effect=OSError('offline')):
            response = self.client.get('/api/weather_warnings')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['error'])

    def test_reverse_geocode_api(self):
        with patch.object(app_module, 'reverse_geocode_coordinates', return_value='青森県青森市新町'):
            response = self.client.get('/api/reverse-geocode?latitude=40.8&longitude=140.7')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['address'], '青森県青森市新町')

    def test_board_validates_and_saves_multiple_values(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        original_instructions = list(app_module.instructions)
        try:
            with patch.object(app_module, 'save_instructions'):
                response = self.client.post('/board', data={'region': '北部'})
                self.assertIn('地域・災害・避難所・緊急度をすべて入力してください。', response.get_data(as_text=True))
                self.assertEqual(app_module.instructions, original_instructions)

                response = self.client.post('/board', data={
                    'region': ['北部', '南部'],
                    'disaster': ['地震', '津波'],
                    'shelter': ['御所見小学校', '片瀬小学校'],
                    'urgency': '高',
                })
            self.assertEqual(response.status_code, 200)
            created = app_module.instructions[0]
            self.assertEqual(created['region'], '北部、南部')
            self.assertEqual(created['disaster'], '地震、津波')
            self.assertEqual(created['shelter'], '御所見小学校、片瀬小学校')
            self.assertEqual(created['other_message'], '')
            self.assertIn('<td></td>', response.get_data(as_text=True))
        finally:
            app_module.instructions[:] = original_instructions

    def test_board_shelter_choices_include_registered_only(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        original_shelters = list(app_module.shelters)
        try:
            app_module.shelters[:] = [
                {'id': 1, 'name': 'サンプル施設'},
                {'id': 2, 'name': '登録済み施設', 'area': '北側', 'congestion': '空きあり', 'opening_status': '受け入れ可'},
            ]
            html = self.client.get('/board').get_data(as_text=True)
            self.assertIn('value="登録済み施設"', html)
            self.assertNotIn('value="サンプル施設"', html)
        finally:
            app_module.shelters[:] = original_shelters


if __name__ == '__main__':
    unittest.main()
