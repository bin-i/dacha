build_ble2mqtt:
	docker build -t smartdacha/ble2mqtt apps/ble2mqtt
	docker save -o ansible/roles/smart_house/files/ble2mqtt/ble2mqtt.tar smartdacha/ble2mqtt

upload: build_ble2mqtt
	cd ansible && ansible-playbook -i hosts smart_house.yaml
