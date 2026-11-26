import boto3
import json
from decimal import Decimal

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("model_result")


def decimal_converter(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError


def lambda_handler(event, context):

    response = table.get_item(
        Key={"id": "LATEST"},
        ConsistentRead=True
    )

    latest = response.get("Item")

    if not latest:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "message": "Nenhum resultado encontrado."
            })
        }

    latest['result'] = bool(latest['result'])

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(latest, default=decimal_converter)
    }