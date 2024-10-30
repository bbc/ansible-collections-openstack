import collections
import inspect
import mock
import pytest
import yaml

from ansible.module_utils.six import string_types
from ansible_collections.openstack.cloud.plugins.modules import server as os_server


class AnsibleFail(Exception):
    pass


class AnsibleExit(Exception):
    pass


def params_from_doc(func):
    '''This function extracts the docstring from the specified function,
    parses it as a YAML document, and returns parameters for the openstack.cloud.server
    module.'''

    doc = inspect.getdoc(func)
    cfg = yaml.load(doc)

    for task in cfg:
        for module, params in task.items():
            for k, v in params.items():
                if k in ['nics'] and isinstance(v, string_types):
                    params[k] = [v]
        task[module] = collections.defaultdict(str,
                                               params)

    return cfg[0]['openstack.cloud.server']


class FakeCloud(object):
    ports = [
        {'name': 'port1', 'id': '1234'},
        {'name': 'port2', 'id': '4321'},
    ]

    networks = [
        {'name': 'network1', 'id': '5678'},
        {'name': 'network2', 'id': '8765'},
    ]

    images = [
        {'name': 'cirros', 'id': '1'},
        {'name': 'fedora', 'id': '2'},
    ]

    flavors = [
        {'name': 'm1.small', 'id': '1', 'flavor_ram': 1024},
        {'name': 'm1.tiny', 'id': '2', 'flavor_ram': 512},
    ]

    def _find(self, source, name):
        for item in source:
            if item['name'] == name or item['id'] == name:
                return item

    def get_image_id(self, name, exclude=None):
        image = self._find(self.images, name)
        if image:
            return image['id']

    def get_flavor(self, name):
        return self._find(self.flavors, name)

    def get_flavor_by_ram(self, ram, include=None):
        for flavor in self.flavors:
            if flavor['ram'] >= ram and (include is None or include in
                                         flavor['name']):
                return flavor

    def get_port(self, name):
        return self._find(self.ports, name)

    def get_network(self, name):
        return self._find(self.networks, name)

    def get_openstack_vars(self, server):
        return server

    create_server = mock.MagicMock()


class TestNetworkArgs(object):
    '''This class exercises the _network_args function of the
    openstack.cloud.server module.  For each test, we parse the YAML document
    contained in the docstring to retrieve the module parameters for the
    test.'''

    def setup_method(self, method):
        self.cloud = FakeCloud()
        self.module = mock.MagicMock()
        self.module.params = params_from_doc(method)

    def test_nics_string_net_id(self):
        '''
        - openstack.cloud.server:
            nics: net-id=1234
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['net-id'] == '1234'

    def test_nics_string_net_id_list(self):
        '''
        - openstack.cloud.server:
            nics: net-id=1234,net-id=4321
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['net-id'] == '1234'
        assert args[1]['net-id'] == '4321'

    def test_nics_string_port_id(self):
        '''
        - openstack.cloud.server:
            nics: port-id=1234
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['port-id'] == '1234'

    def test_nics_string_net_name(self):
        '''
        - openstack.cloud.server:
            nics: net-name=network1
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['net-id'] == '5678'

    def test_nics_string_port_name(self):
        '''
        - openstack.cloud.server:
            nics: port-name=port1
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['port-id'] == '1234'

    def test_nics_structured_net_id(self):
        '''
        - openstack.cloud.server:
            nics:
                - net-id: '1234'
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['net-id'] == '1234'

    def test_nics_structured_mixed(self):
        '''
        - openstack.cloud.server:
            nics:
                - net-id: '1234'
                - port-name: port1
                - 'net-name=network1,port-id=4321'
        '''
        args = os_server._network_args(self.module, self.cloud)
        assert args[0]['net-id'] == '1234'
        assert args[1]['port-id'] == '1234'
        assert args[2]['net-id'] == '5678'
        assert args[3]['port-id'] == '4321'


class TestCreateServer(object):
    def setup_method(self, method):
        self.cloud = FakeCloud()
        self.module = mock.MagicMock()
        self.module.params = params_from_doc(method)
        self.module.fail_json.side_effect = AnsibleFail()
        self.module.exit_json.side_effect = AnsibleExit()

        self.meta = mock.MagicMock()
        self.meta.gett_hostvars_from_server.return_value = {
            'id': '1234'
        }
        os_server.meta = self.meta

    def test_create_server(self):
        '''
        - openstack.cloud.server:
            image: cirros
            flavor: m1.tiny
            nics:
              - net-name: network1
            meta:
              - key: value
        '''
        with pytest.raises(AnsibleExit):
            os_server._create_server(self.module, self.cloud)

        assert self.cloud.create_server.call_count == 1
        assert self.cloud.create_server.call_args[1]['image'] == self.cloud.get_image_id('cirros')
        assert self.cloud.create_server.call_args[1]['flavor'] == self.cloud.get_flavor('m1.tiny')['id']
        assert self.cloud.create_server.call_args[1]['nics'][0]['net-id'] == self.cloud.get_network('network1')['id']

    def test_create_server_bad_flavor(self):
        '''
        - openstack.cloud.server:
            image: cirros
            flavor: missing_flavor
            nics:
              - net-name: network1
        '''
        with pytest.raises(AnsibleFail):
            os_server._create_server(self.module, self.cloud)

        assert 'missing_flavor' in self.module.fail_json.call_args[1]['msg']

    def test_create_server_bad_nic(self):
        '''
        - openstack.cloud.server:
            image: cirros
            flavor: m1.tiny
            nics:
              - net-name: missing_network
        '''
        with pytest.raises(AnsibleFail):
            os_server._create_server(self.module, self.cloud)

        assert 'missing_network' in self.module.fail_json.call_args[1]['msg']

    def test_create_server_auto_ip_wait(self):
        '''
        - openstack.cloud.server:
            image: cirros
            auto_ip: true
            wait: false
            nics:
              - net-name: network1
        '''
        with pytest.raises(AnsibleFail):
            os_server._create_server(self.module, self.cloud)

        assert 'auto_ip' in self.module.fail_json.call_args[1]['msg']

    def test_create_server_floating_ips_wait(self):
        '''
        - openstack.cloud.server:
            image: cirros
            floating_ips: ['0.0.0.0']
            wait: false
            nics:
              - net-name: network1
        '''
        with pytest.raises(AnsibleFail):
            os_server._create_server(self.module, self.cloud)

        assert 'floating_ips' in self.module.fail_json.call_args[1]['msg']

    def test_create_server_floating_ip_pools_wait(self):
        '''
        - openstack.cloud.server:
            image: cirros
            floating_ip_pools: ['name-of-pool']
            wait: false
            nics:
              - net-name: network1
        '''
        with pytest.raises(AnsibleFail):
            os_server._create_server(self.module, self.cloud)

        assert 'floating_ip_pools' in self.module.fail_json.call_args[1]['msg']
