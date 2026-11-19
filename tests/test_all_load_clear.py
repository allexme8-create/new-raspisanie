import copy
from test_department_load_clear import ClearDepartmentLoadTests

class ClearAllLoadTests(ClearDepartmentLoadTests):
    def test_all_load_clear(self):
        url='/api/admin/planner/all-load/clear';before=copy.deepcopy(app.state)
        self.assertEqual(self.client.post(url,json={'revision':0}).status_code,401)
        self.assertEqual(self.client.post(url,headers=self.auth,json={'revision':1}).status_code,409)
        r=self.client.post(url,headers=self.auth,json={'revision':0});self.assertEqual(r.status_code,200,r.text)
        data=r.json();self.assertEqual(data['removed'],5);self.assertEqual(data['project']['loads'],[]);self.assertEqual(data['project']['teachers'],before['planner']['teachers']);self.assertEqual(data['project']['departments'],before['planner']['departments']);self.assertEqual(app.state['teachers'],before['teachers']);self.assertEqual(data['project']['revision'],1)
        self.assertEqual(self.client.post(url,headers=self.auth,json={'revision':0}).status_code,409)
        r=self.client.post(url,headers=self.auth,json={'revision':1});self.assertEqual(r.json()['removed'],0);self.assertEqual(self.save.call_count,1)
    def test_placed_blocks_entire_clear(self):
        app.state['planner']['placements']=[{'load_id':'4','day':'Пн','lesson':1,'room':''}];before=copy.deepcopy(app.state['planner'])
        r=self.client.post('/api/admin/planner/all-load/clear',headers=self.auth,json={'revision':0});self.assertEqual(r.status_code,409);self.assertEqual(app.state['planner'],before);self.save.assert_not_called()

import app
