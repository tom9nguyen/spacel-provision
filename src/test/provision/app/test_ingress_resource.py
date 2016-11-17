import six
from botocore.exceptions import ClientError
from mock import MagicMock

from spacel.aws import ClientCache
from spacel.provision.app.ingress_resource import IngressResourceFactory
from test import BaseSpaceAppTest, ORBIT_REGION

OTHER_REGION = 'us-east-1'
IP_BLOCK = '127.0.0.1/32'
SECURITY_GROUP = 'sg-123456'
ELASTIC_IP = '1.1.1.1'


class TestIngressResourceFactory(BaseSpaceAppTest):
    def setUp(self):
        super(TestIngressResourceFactory, self).setUp()
        self.cloudformation = MagicMock()
        self.clients = MagicMock(speck=ClientCache)
        self.clients.cloudformation.return_value = self.cloudformation
        self.ingress = IngressResourceFactory(self.clients)
        for az_index, az in enumerate(self.other_orbit_region.azs.values()):
            az.nat_eip = '{0}.{0}.{0}.{0}'.format(az_index)
        self._multi_region()

    def test_ingress_resources_ip_block(self):
        resource = self._only(self._http_ingress(IP_BLOCK))
        self.assertEquals(IP_BLOCK, resource['Properties']['CidrIp'])

    def test_ingress_resources_region(self):
        resource = self._only(self._http_ingress(ORBIT_REGION))
        self.assertEquals('192.168.0.0/16', resource['Properties']['CidrIp'])

    def test_ingress_resources_other_region_nat(self):
        self.ingress._app_eips = MagicMock(return_value=[])
        resources = self._http_ingress(OTHER_REGION)
        # 1 per Nat EIP:
        self.assertEquals(3, len(resources))
        for resource in resources.values():
            self.assertIn('CidrIp', resource['Properties'])

    def test_ingress_resources_other_region(self):
        self.ingress._app_eips = MagicMock(return_value=['1.1.1.1', '2.2.2.2'])
        resources = self._http_ingress(OTHER_REGION)
        # 1 per App EIP:
        self.assertEquals(2, len(resources))
        for resource in resources.values():
            self.assertIn('CidrIp', resource['Properties'])

    def test_ingress_resource_app(self):
        self.ingress._app_sg = MagicMock(return_value=SECURITY_GROUP)
        resource = self._only(self._http_ingress('foo'))
        self.assertNotIn('CidrIp', resource['Properties'])
        self.assertEquals(SECURITY_GROUP,
                          resource['Properties']['SourceSecurityGroupId'])

    def test_ingress_resource_app_not_found(self):
        self.ingress._app_sg = MagicMock(return_value=None)
        resources = self._http_ingress('foo')
        self.assertEquals(0, len(resources))

    def test_app_sg(self):
        self.cloudformation.describe_stack_resource.return_value = {
            'StackResourceDetail': {
                'PhysicalResourceId': SECURITY_GROUP
            }
        }
        sg = self.ingress._app_sg(self.orbit, ORBIT_REGION, 'test-app')
        self.assertEquals(SECURITY_GROUP, sg)

    def test_app_sg_not_found(self):
        self._describe_stack_resource_error('Stack does not exist')
        sg = self.ingress._app_sg(self.orbit, ORBIT_REGION, 'test-app')
        self.assertIsNone(sg)

    def test_app_sg_error(self):
        self._describe_stack_resource_error('Kaboom')
        self.assertRaises(ClientError, self.ingress._app_sg, self.orbit,
                          ORBIT_REGION, 'test-app')

    def test_app_eips(self):
        resource_list = [{
            'StackResourceSummaries': [{
                'LogicalResourceId': 'ElasticIp01',
                'PhysicalResourceId': ELASTIC_IP
            }]
        }]
        pages = MagicMock()
        pages.paginate = MagicMock(return_value=resource_list)
        self.cloudformation.get_paginator = MagicMock(return_value=pages)

        eips = self.ingress._app_eips(self.orbit_region, 'test-app')
        self.assertIn(ELASTIC_IP, eips)

    def test_app_eips_error(self):
        self.cloudformation.get_paginator.side_effect = ClientError({
            'Error': {
                'Message': 'Kaboom'
            }
        }, 'GetPaginator')
        self.assertRaises(ClientError, self.ingress._app_eips,
                          self.orbit_region, 'test-app')

    def test_app_eips_cloudformation_stack_does_not_exist(self):
        self.cloudformation.get_paginator.side_effect = ClientError({
            'Error': {
                'Message': 'CloudFormation stack does not exist'
            }
        }, 'GetPaginator')
        eips = self.ingress._app_eips(self.orbit_region, 'test-app')
        self.assertEquals(0, len(eips))

    def _http_ingress(self, *args):
        return self.ingress.ingress_resources(self.orbit, ORBIT_REGION, 80,
                                              args)

    def _only(self, resources):
        self.assertEquals(1, len(resources))
        return six.next(six.itervalues(resources))

    def _describe_stack_resource_error(self, message):
        self.cloudformation.describe_stack_resource.side_effect = ClientError({
            'Error': {
                'Message': message
            }
        }, 'CreateSubnet')