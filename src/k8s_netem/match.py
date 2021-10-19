from kubernetes import client
from kubernetes.client.models import V1LabelSelector

from typing import Union

class LabelSelector:

    def __init__(self, obj: Union[dict, V1LabelSelector]):
        if obj is not V1LabelSelector:
            v1 = client.CoreV1Api()
            obj = v1.api_client._ApiClient__deserialize(obj, 'V1LabelSelector')

        self.match_labels = obj.match_labels or {}
        self.match_expressions = obj.match_expressions or []

        self.expressions = self.match_expressions

        # Convert matchLabels into matchExpressions
        for key, value in self.match_labels.items():
            self.expressions.append({
                'key': key,
                'values': [value],
                'operator': 'In'
            })

    def to_labelselector(self):
        exprs = []
        for expr in self.expressions:
            op = expr.get('operator', 'In')
            key = expr.get('key')
            values = expr.get('values', [])
            values_list = ','.join(values)

            if op == 'In':
                exprs.append(f'{key} in ({values_list})')
            elif op == 'NotIn':
                exprs.append(f'{key} notin ({values_list})')
            elif op == 'Exists':
                exprs.append(f'{key}')
            elif op == 'DoesNotExist':
                exprs.append(f'!{key}')

        return ','.join(exprs)

    def match(self, labels) -> bool:
        # An empty label selector matches all objects.
        if len(self.expressions) == 0:
            return True

        for expr in self.expressions:
            key = expr.get('key')
            vals = expr.get('values')
            op = expr.get('operator')

            val = labels.get(key)

            match = False
            if op == 'In':
                match = val in vals
            elif op == 'NotIn':
                match = val not in vals
            elif op == 'Exists':
                match = key in labels
            elif op == 'DoesNotExist':
                match = key not in labels

            if match:
                return True

        return False
