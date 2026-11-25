# deploy_scramble_dynamo.py
# Despliega EC2 + Security Group nuevo + DynamoDB (crea o reutiliza) para Scramble Mini-Blockchain.

import json
import time
import urllib.request
import boto3
from botocore.exceptions import ClientError

# Reemplaza esta URL con la de tu repositorio de GitHub que contiene el proyecto Scramble
GITHUB_REPO_URL = "https://github.com/TU_USUARIO/TU_REPO_SCRAMBLE.git"


def generar_user_data(region_name, table_name):
    """Instala git, clona el proyecto Scramble desde GitHub y levanta FastAPI con Uvicorn en el puerto 80."""
    return f"""#!/bin/bash
yum update -y
yum install -y python3-pip git

rm -rf /opt/scramble_app
git clone {GITHUB_REPO_URL} /opt/scramble_app
pip3 install -r /opt/scramble_app/requirements.txt

cat << EOF > /etc/systemd/system/scramble.service
[Unit]
Description=Servicio Web Scramble Mini-Blockchain (FastAPI)
After=network.target

[Service]
User=root
WorkingDirectory=/opt/scramble_app
Environment="AWS_REGION={region_name}"
Environment="TABLE_NAME={table_name}"
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 80
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable scramble.service
systemctl start scramble.service
"""


def configurar_perfil_iam(iam_client):
    """Detecta LabInstanceProfile (AWS Academy) o crea un IAM Role temporal para DynamoDB."""
    try:
        iam_client.get_instance_profile(InstanceProfileName="LabInstanceProfile")
        print("Perfil IAM detectado: LabInstanceProfile (AWS Academy).")
        return "LabInstanceProfile", False
    except ClientError:
        pass

    role_name = "RoleScrambleEC2"
    profile_name = "ProfileScrambleEC2"
    assume_policy = """{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }"""

    try:
        print(f"Creando perfil IAM '{profile_name}' para acceso a DynamoDB...")
        iam_client.create_role(RoleName=role_name, AssumeRolePolicyDocument=assume_policy)
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
        )
        iam_client.create_instance_profile(InstanceProfileName=profile_name)
        iam_client.add_role_to_instance_profile(
            InstanceProfileName=profile_name,
            RoleName=role_name
        )
        time.sleep(10)
        return profile_name, True
    except ClientError as e:
        print(f"Aviso IAM: {e}")
        return None, False


def crear_grupo_seguridad(ec2_client, group_name):
    """Crea un Security Group nuevo desde cero abriendo puertos 22 (SSH) y 80 (HTTP)."""
    print(f"\nCreando Security Group nuevo: '{group_name}'...")
    vpcs = ec2_client.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    vpc_id = vpcs["Vpcs"][0]["VpcId"]

    sg = ec2_client.create_security_group(
        GroupName=group_name,
        Description="Security Group para Scramble Mini-Blockchain (HTTP y SSH)",
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [{"Key": "Name", "Value": group_name}]
            }
        ]
    )
    security_group_id = sg["GroupId"]

    ec2_client.authorize_security_group_ingress(
        GroupId=security_group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Acceso SSH"}]
            },
            {
                "IpProtocol": "tcp",
                "FromPort": 80,
                "ToPort": 80,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Acceso Web HTTP"}]
            }
        ]
    )
    print(f"Confirmacion: Security Group creado con ID: {security_group_id}")
    return security_group_id


def asegurar_tabla_dynamodb(dynamodb_client, table_name):
    """Verifica si la tabla DynamoDB existe: si existe la reutiliza, si no la crea."""
    print(f"\nVerificando tabla DynamoDB '{table_name}'...")
    try:
        dynamodb_client.describe_table(TableName=table_name)
        print(f"Confirmacion: La tabla '{table_name}' YA EXISTIA. Se reutilizara con sus datos actuales.")
        return True, False  # (tabla_disponible, fue_creada_ahora)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    print(f"La tabla '{table_name}' no existe. Creandola en modo On-Demand...")
    dynamodb_client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
        Tags=[{"Key": "Name", "Value": table_name}]
    )
    print("Esperando a que la tabla DynamoDB este activa...")
    waiter_table = dynamodb_client.get_waiter("table_exists")
    waiter_table.wait(TableName=table_name)
    print(f"Confirmacion: Tabla DynamoDB '{table_name}' creada y activa.")
    return True, True


def crear_instancia_ec2(ec2_client, region_name, image_id, instance_type, key_name, security_group_id, table_name, profile_name=None):
    """Crea la instancia EC2 con UserData, espera estado 'running' y retorna su ID."""
    print("\nIntentando crear la instancia EC2...")
    user_data = generar_user_data(region_name, table_name)

    run_params = {
        "ImageId": image_id,
        "InstanceType": instance_type,
        "KeyName": key_name,
        "SecurityGroupIds": [security_group_id],
        "UserData": user_data,
        "MinCount": 1,
        "MaxCount": 1,
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "Servidor Web - Scramble Blockchain"}]
            }
        ]
    }

    if profile_name:
        run_params["IamInstanceProfile"] = {"Name": profile_name}

    response = ec2_client.run_instances(**run_params)
    instance_id = response["Instances"][0]["InstanceId"]
    print(f"Instancia iniciada. ID: {instance_id}")

    print("Esperando a que la instancia cambie a estado 'running'...")
    waiter_running = ec2_client.get_waiter("instance_running")
    waiter_running.wait(InstanceIds=[instance_id])
    print("Confirmacion: La instancia se encuentra en estado 'running'.")

    return instance_id


def ver_estado_instancia(ec2_client, instance_id, key_name):
    """Consulta el estado actual de la EC2, su IP publica y verifica si FastAPI responde."""
    try:
        desc = ec2_client.describe_instances(InstanceIds=[instance_id])
        instancia = desc["Reservations"][0]["Instances"][0]
        estado = instancia["State"]["Name"]
        tipo = instancia["InstanceType"]
        zona = instancia["Placement"]["AvailabilityZone"]
        public_ip = instancia.get("PublicIpAddress", "No asignada (instancia detenida)")

        print("\n--- Estado de la Instancia EC2 ---")
        print(f"ID Instancia   : {instance_id}")
        print(f"Estado AWS     : {estado.upper()}")
        print(f"Tipo / Zona    : {tipo} ({zona})")
        print(f"IP Publica     : {public_ip}")

        if estado == "running" and public_ip != "No asignada (instancia detenida)":
            print(f"URL Web        : http://{public_ip}")
            print(f"Comando SSH    : ssh -i '{key_name}.pem' ec2-user@{public_ip}")
            try:
                with urllib.request.urlopen(f"http://{public_ip}/health", timeout=3) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        print(f"Servidor Web   : EN LINEA (HTTP 200 OK | Tabla: {data.get('table')})")
            except Exception:
                print("Servidor Web   : INICIANDO O NO DISPONIBLE (espera ~45-60s si acaba de arrancar)")
        print("----------------------------------")
    except ClientError as e:
        print(f"Error al consultar estado de EC2: {e}")


def ver_estado_bd(dynamodb_client, table_name):
    """Consulta el estado de DynamoDB, modo operativo, animales cargados y bloques minados."""
    try:
        resp = dynamodb_client.describe_table(TableName=table_name)
        tabla = resp["Table"]
        estado_aws = tabla["TableStatus"]
        tamano_bytes = tabla["TableSizeBytes"]

        control = dynamodb_client.get_item(
            TableName=table_name,
            Key={"pk": {"S": "CONFIG#ESTADO_BD"}}
        )
        pausada = control.get("Item", {}).get("pausada", {}).get("BOOL", False)
        modo_operativo = "PAUSADA (Modo mantenimiento)" if pausada else "ACTIVA (Operando normal)"

        scan_resp = dynamodb_client.scan(TableName=table_name)
        items = scan_resp.get("Items", [])

        total_animales = sum(1 for it in items if it.get("tipo", {}).get("S") == "ANIMAL")
        total_bloques = sum(1 for it in items if it.get("tipo", {}).get("S") == "BLOQUE")

        print("\n--- Estado de Base de Datos DynamoDB ---")
        print(f"Nombre Tabla       : {table_name}")
        print(f"Estado AWS         : {estado_aws}")
        print(f"Modo Operativo     : {modo_operativo}")
        print(f"Animales catalogo  : {total_animales}")
        print(f"Bloques minados    : {total_bloques}")
        print(f"Tamano ocupado     : {tamano_bytes} bytes")
        print("----------------------------------------")
    except ClientError as e:
        print(f"Error al consultar estado de DynamoDB: {e}")


def pausar_bd(dynamodb_client, table_name):
    """Pausa la base de datos activando el modo mantenimiento para suspender escrituras."""
    try:
        control = dynamodb_client.get_item(
            TableName=table_name,
            Key={"pk": {"S": "CONFIG#ESTADO_BD"}}
        )
        if control.get("Item", {}).get("pausada", {}).get("BOOL", False):
            print("\nAviso: La base de datos ya se encuentra pausada.")
            return

        print(f"\nPausando base de datos '{table_name}'...")
        dynamodb_client.put_item(
            TableName=table_name,
            Item={
                "pk": {"S": "CONFIG#ESTADO_BD"},
                "tipo": {"S": "CONFIG"},
                "pausada": {"BOOL": True}
            }
        )
        print("Confirmacion: Base de datos PAUSADA. El minado de bloques y ataques estan bloqueados.")
    except ClientError as e:
        print(f"Error al pausar la base de datos: {e}")


def reanudar_bd(dynamodb_client, table_name):
    """Reanuda la operacion normal de la base de datos DynamoDB."""
    try:
        control = dynamodb_client.get_item(
            TableName=table_name,
            Key={"pk": {"S": "CONFIG#ESTADO_BD"}}
        )
        if not control.get("Item", {}).get("pausada", {}).get("BOOL", False):
            print("\nAviso: La base de datos ya se encuentra activa.")
            return

        print(f"\nReanudando base de datos '{table_name}'...")
        dynamodb_client.delete_item(
            TableName=table_name,
            Key={"pk": {"S": "CONFIG#ESTADO_BD"}}
        )
        print("Confirmacion: Base de datos REANUDADA y lista para registrar bloques.")
    except ClientError as e:
        print(f"Error al reanudar la base de datos: {e}")


def pausar_instancia_ec2(ec2_client, instance_id):
    """Detiene (pausa) la instancia EC2 si se encuentra en ejecucion."""
    try:
        desc = ec2_client.describe_instances(InstanceIds=[instance_id])
        estado_actual = desc["Reservations"][0]["Instances"][0]["State"]["Name"]

        if estado_actual == "stopped":
            print("\nAviso: La instancia ya se encuentra detenida ('stopped').")
            return

        print(f"\nDeteniendo (pausando) la instancia {instance_id}...")
        ec2_client.stop_instances(InstanceIds=[instance_id])

        print("Esperando a que la instancia cambie a estado 'stopped'...")
        waiter_stopped = ec2_client.get_waiter("instance_stopped")
        waiter_stopped.wait(InstanceIds=[instance_id])
        print("Confirmacion: La instancia se ha detenido correctamente.")
    except ClientError as e:
        print(f"Error al detener la instancia: {e}")


def reanudar_instancia_ec2(ec2_client, instance_id, key_name):
    """Inicia nuevamente una instancia EC2 detenida y muestra su nueva IP publica."""
    try:
        desc = ec2_client.describe_instances(InstanceIds=[instance_id])
        estado_actual = desc["Reservations"][0]["Instances"][0]["State"]["Name"]

        if estado_actual == "running":
            print("\nAviso: La instancia ya se encuentra en ejecucion ('running').")
            return

        print(f"\nIniciando nuevamente la instancia {instance_id}...")
        ec2_client.start_instances(InstanceIds=[instance_id])

        print("Esperando a que la instancia cambie a estado 'running'...")
        waiter_running = ec2_client.get_waiter("instance_running")
        waiter_running.wait(InstanceIds=[instance_id])
        print("Confirmacion: La instancia vuelve a estar en estado 'running'.")
        ver_estado_instancia(ec2_client, instance_id, key_name)
    except ClientError as e:
        print(f"Error al reanudar la instancia: {e}")


def destruir_instancia_ec2(ec2_client, instance_id):
    """Detiene (si esta activa) y termina/elimina definitivamente la instancia EC2."""
    try:
        desc = ec2_client.describe_instances(InstanceIds=[instance_id])
        estado_actual = desc["Reservations"][0]["Instances"][0]["State"]["Name"]

        if estado_actual == "terminated":
            print("La instancia ya habia sido eliminada.")
            return

        if estado_actual == "running":
            pausar_instancia_ec2(ec2_client, instance_id)

        print(f"\nProcediendo a eliminar (terminar) la instancia {instance_id}...")
        ec2_client.terminate_instances(InstanceIds=[instance_id])

        print("Esperando a que la instancia cambie a estado 'terminated'...")
        waiter_terminated = ec2_client.get_waiter("instance_terminated")
        waiter_terminated.wait(InstanceIds=[instance_id])
        print("Confirmacion: La instancia ha sido terminada/eliminada exitosamente.")
    except ClientError as e:
        print(f"Error al eliminar la instancia EC2: {e}")


def destruir_recursos_auxiliares(
    ec2_client,
    dynamodb_client,
    iam_client,
    security_group_id,
    table_name,
    eliminar_bd,
    eliminar_iam
):
    """Elimina Security Group, IAM temporal y opcionalmente la tabla DynamoDB."""
    if eliminar_bd and table_name:
        try:
            print(f"\nEliminando tabla DynamoDB '{table_name}'...")
            dynamodb_client.delete_table(TableName=table_name)
            waiter_deleted = dynamodb_client.get_waiter("table_not_exists")
            waiter_deleted.wait(TableName=table_name)
            print("Confirmacion: Tabla DynamoDB eliminada.")
        except ClientError as e:
            print(f"Error eliminando tabla DynamoDB: {e}")
    elif table_name:
        print(f"\nConservando tabla DynamoDB '{table_name}' con todos sus registros intactos.")

    if security_group_id:
        try:
            print(f"Eliminando Security Group '{security_group_id}'...")
            ec2_client.delete_security_group(GroupId=security_group_id)
            print("Confirmacion: Security Group eliminado.")
        except ClientError as e:
            print(f"Error eliminando Security Group: {e}")

    if eliminar_iam:
        try:
            iam_client.remove_role_from_instance_profile(
                InstanceProfileName="ProfileScrambleEC2",
                RoleName="RoleScrambleEC2"
            )
            iam_client.delete_instance_profile(InstanceProfileName="ProfileScrambleEC2")
            iam_client.detach_role_policy(
                RoleName="RoleScrambleEC2",
                PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
            )
            iam_client.delete_role(RoleName="RoleScrambleEC2")
            print("Confirmacion: Perfil y rol IAM eliminados.")
        except ClientError as e:
            print(f"Error eliminando recursos IAM: {e}")


def menu_interactivo(ec2_client, dynamodb_client, instance_id, table_name, key_name):
    """Bucle de control interactivo. Retorna True si se debe borrar la BD al salir, False si se conserva."""
    while True:
        print("\n==========================================================")
        print("   PANEL DE CONTROL AWS - SCRAMBLE MINI-BLOCKCHAIN        ")
        print("==========================================================")
        print(" 1.- Ver estado de la instancia EC2 (y salud web)")
        print(" 2.- Ver estado de la base de datos DynamoDB")
        print(" 3.- Pausar (detener) instancia EC2")
        print(" 4.- Reanudar (encender) instancia EC2")
        print(" 5.- Pausar base de datos DynamoDB")
        print(" 6.- Reanudar base de datos DynamoDB")
        print(" 7.- Destruir EC2 + Security Group y CONSERVAR DynamoDB")
        print(" 8.- Destruir TODA la infraestructura (incluyendo DynamoDB)")
        print("==========================================================")

        opcion = input("Selecciona una opcion (1-8): ").strip()

        if opcion == "1":
            ver_estado_instancia(ec2_client, instance_id, key_name)
        elif opcion == "2":
            ver_estado_bd(dynamodb_client, table_name)
        elif opcion == "3":
            pausar_instancia_ec2(ec2_client, instance_id)
        elif opcion == "4":
            reanudar_instancia_ec2(ec2_client, instance_id, key_name)
        elif opcion == "5":
            pausar_bd(dynamodb_client, table_name)
        elif opcion == "6":
            reanudar_bd(dynamodb_client, table_name)
        elif opcion == "7":
            confirmar = input(
                f"¿Eliminar EC2 y Security Group pero CONSERVAR la tabla '{table_name}'? (s/n): "
            ).strip().lower()
            if confirmar == "s":
                print("\nEliminando computo y red (conservando DynamoDB)...")
                return False
            print("Operacion cancelada. Regresando al menu...")
        elif opcion == "8":
            confirmar = input(
                f"¿Seguro que deseas eliminar EC2, Security Group Y la tabla '{table_name}'? (s/n): "
            ).strip().lower()
            if confirmar == "s":
                print("\nIniciando destruccion completa de todos los recursos...")
                return True
            print("Operacion cancelada. Regresando al menu...")
        else:
            print("Opcion no valida. Por favor elige un numero del 1 al 8.")
        input("\nPresiona ENTER para volver al menu...")


def lifecycle(region_name, image_id, instance_type, key_name):
    """Orquesta la creacion/reutilizacion automatica, el menu interactivo y la limpieza elegida."""
    ec2_client = boto3.client("ec2", region_name=region_name)
    dynamodb_client = boto3.client("dynamodb", region_name=region_name)
    iam_client = boto3.client("iam", region_name=region_name)

    sufijo = str(int(time.time()))[-4:]
    sg_name = f"secgroup-scramble-{sufijo}"
    table_name = "ScrambleBlockchain"

    security_group_id = None
    instance_id = None
    tabla_disponible = False
    eliminar_iam = False
    eliminar_bd_al_salir = False  # Por defecto se protege la BD ante interrupciones inesperadas

    try:
        # 1. Configurar IAM, Security Group y DynamoDB (crea o reutiliza)
        profile_name, eliminar_iam = configurar_perfil_iam(iam_client)
        security_group_id = crear_grupo_seguridad(ec2_client, sg_name)
        tabla_disponible, _ = asegurar_tabla_dynamodb(dynamodb_client, table_name)

        # 2. Crear y arrancar la instancia EC2
        instance_id = crear_instancia_ec2(
            ec2_client=ec2_client,
            region_name=region_name,
            image_id=image_id,
            instance_type=instance_type,
            key_name=key_name,
            security_group_id=security_group_id,
            table_name=table_name,
            profile_name=profile_name
        )

        ver_estado_instancia(ec2_client, instance_id, key_name)

        # 3. Entrar al bucle de menu interactivo
        eliminar_bd_al_salir = menu_interactivo(
            ec2_client, dynamodb_client, instance_id, table_name, key_name
        )

    except ClientError as e:
        print(f"ERROR en el ciclo de vida de la infraestructura: {e}")
    except KeyboardInterrupt:
        print("\nInterrupcion detectada (Ctrl+C). Eliminando EC2/red y conservando DynamoDB por seguridad...")

    finally:
        if instance_id:
            destruir_instancia_ec2(ec2_client, instance_id)
        destruir_recursos_auxiliares(
            ec2_client=ec2_client,
            dynamodb_client=dynamodb_client,
            iam_client=iam_client,
            security_group_id=security_group_id,
            table_name=table_name if tabla_disponible else None,
            eliminar_bd=eliminar_bd_al_salir,
            eliminar_iam=eliminar_iam
        )
        if eliminar_bd_al_salir:
            print("\nTodo el entorno (incluida la BD) ha sido eliminado. Costo residual: $0.00.")
        else:
            print(f"\nInstancia EC2 y red eliminadas. La tabla '{table_name}' sigue disponible en DynamoDB.")
            


if __name__ == "__main__":
    AWS_REGION = "us-east-1"
    AMI_ID = "ami-09bf9dfeeb1e9adbc"
    INSTANCE_TYPE = "t3.micro"
    KEY_PAIR_NAME = "vockey"

    lifecycle(
        region_name=AWS_REGION,
        image_id=AMI_ID,
        instance_type=INSTANCE_TYPE,
        key_name=KEY_PAIR_NAME
    )