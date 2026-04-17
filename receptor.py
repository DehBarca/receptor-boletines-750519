import boto3
import json
import time
from datetime import datetime
from threading import Thread

# Configurar clientes de AWS
sqs_client = boto3.client('sqs', region_name='us-east-1')
sns_client = boto3.client('sns', region_name='us-east-1')
dynamodb_client = boto3.client('dynamodb', region_name='us-east-1')
dynamodb_resource = boto3.resource('dynamodb', region_name='us-east-1')

QUEUE_NAME = "cola-boletines"
TABLE_NAME = "boletines"
TOPIC_NAME = "notificaciones-boletines"
QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/828936183282/cola-boletines"
# SNS_TOPIC_ARN se obtendrá dinámicamente en la función enviar_notificacion_sns
SNS_TOPIC_ARN = None


def inicializar_base_datos():
    """
    Verifica que la tabla DynamoDB existe. Si no, la crea.
    """
    try:
        table = dynamodb_resource.Table(TABLE_NAME)
        table.load()
        print(f"Tabla DynamoDB '{TABLE_NAME}' ya existe")
    except Exception:
        print("Tabla no existe, intentando crear...")
        try:
            table = dynamodb_resource.create_table(
                TableName=TABLE_NAME,
                KeySchema=[
                    {'AttributeName': 'id', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'id', 'AttributeType': 'S'}
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            print(f"Tabla '{TABLE_NAME}' creada exitosamente")
            table.wait_until_exists()
            print("Tabla lista para usar")
        except Exception as create_error:
            print(f"Error al crear tabla: {str(create_error)}")


def guardar_en_base_datos(boletin_id, contenido, correo, imagen_url, nombre_archivo):
    """
    Guarda el boletín en DynamoDB.
    """
    try:
        table = dynamodb_resource.Table(TABLE_NAME)
        
        item = {
            'id': boletin_id,
            'contenido': contenido,
            'correo_electronico': correo,
            'imagen_url': imagen_url,
            'nombre_archivo': nombre_archivo,
            'leido': 0,
            'fecha_creacion': datetime.now().isoformat()
        }
        
        table.put_item(Item=item)
        print(f"Boletín {boletin_id} guardado en DynamoDB")
        return True
    except Exception as e:
        print(f"Error al guardar en DynamoDB: {str(e)}")
        return False


def enviar_notificacion_sns(correo, boletin_id, imagen_url):
    """
    Envía una notificación por SNS al correo del usuario.
    """
    try:
        global SNS_TOPIC_ARN
        
        # Obtener o crear el topic SNS
        if not SNS_TOPIC_ARN:
            # Buscar si el topic ya existe
            topics = sns_client.list_topics()['Topics']
            topic_found = False
            
            for topic in topics:
                if TOPIC_NAME in topic['TopicArn']:
                    SNS_TOPIC_ARN = topic['TopicArn']
                    topic_found = True
                    print(f"✓ Topic SNS encontrado: {SNS_TOPIC_ARN}")
                    break
            
            # Si no existe, créalo
            if not topic_found:
                response = sns_client.create_topic(Name=TOPIC_NAME)
                SNS_TOPIC_ARN = response['TopicArn']
                print(f"✓ Topic SNS creado: {SNS_TOPIC_ARN}")
        
        # Preparar el mensaje
        asunto = f"Nuevo boletín disponible - ID: {boletin_id}"
        cuerpo = f"""Estimado usuario,

Se ha generado un nuevo boletín para usted.

ID del boletín: {boletin_id}
Ver boletín: http://localhost:8002/boletines/{boletin_id}?correoElectronico={correo}

Imagen: {imagen_url}

Atentamente,
Sistema de Boletines
"""
        
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=asunto,
            Message=cuerpo
        )
        print(f"📧 Notificación enviada a {correo}")
        return True
    except Exception as e:
        print(f"⚠️  SNS no disponible (opcional): {str(e)}")
        return True  # Retorna True para no frenar el proceso


def procesar_mensaje(mensaje_body):
    """
    Procesa un mensaje recibido de la cola SQS.
    """
    try:
        mensaje = json.loads(mensaje_body)
        
        boletin_id = mensaje.get('boletin_id')
        contenido = mensaje.get('contenido')
        correo = mensaje.get('correoElectronico')
        imagen_url = mensaje.get('imagen_url')
        nombre_archivo = mensaje.get('nombre_archivo')
        
        print(f"Procesando boletín {boletin_id}...")
        
        # Guardar en base de datos
        if guardar_en_base_datos(boletin_id, contenido, correo, imagen_url, nombre_archivo):
            # Enviar notificación SNS
            enviar_notificacion_sns(correo, boletin_id, imagen_url)
            print(f"Boletín {boletin_id} procesado exitosamente")
            return True
        else:
            print(f"Error al procesar boletín {boletin_id}")
            return False
    
    except Exception as e:
        print(f"Error al procesar mensaje: {str(e)}")
        return False


def consumir():
    """
    Monitorea la cola SQS y procesa los mensajes continuamente.
    """
    try:
        # Obtener URL de la cola
        queue_response = sqs_client.get_queue_url(QueueName=QUEUE_NAME)
        queue_url = queue_response['QueueUrl']
        print(f"Cola SQS obtenida: {queue_url}")
        
        while True:
            # Esperar mensajes de SQS
            response = sqs_client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20  # Long polling
            )
            
            if 'Messages' in response:
                print(f"✓ {len(response['Messages'])} mensaje(s) recibido(s)")
                for mensaje in response['Messages']:
                    print(f"📨 Procesando: {mensaje['Body'][:100]}...")
                    # Procesar el mensaje
                    if procesar_mensaje(mensaje['Body']):
                        # Eliminar mensaje de la cola después de procesarlo
                        sqs_client.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=mensaje['ReceiptHandle']
                        )
                        print("✓ Mensaje eliminado de la cola")
                    else:
                        print("✗ Error al procesar mensaje")
            else:
                print("⏳ Sin mensajes en la cola, esperando...")
            
            time.sleep(5)
    
    except Exception as e:
        print(f"❌ Error en el consumidor SQS: {str(e)}")
        # Reintentar conexión después de un tiempo
        time.sleep(10)
        consumir()


if __name__ == "__main__":
    print("Servicio receptor listo")
    print(f"Inicializando tabla DynamoDB '{TABLE_NAME}'...")
    inicializar_base_datos()
    print("Base de datos inicializada")
    
    print("Iniciando consumidor de mensajes SQS...")
    # Ejecutar en un hilo separado
    thread = Thread(target=consumir, daemon=True)
    thread.start()
    
    # Mantener el proceso activo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServicio receptor detenido")
