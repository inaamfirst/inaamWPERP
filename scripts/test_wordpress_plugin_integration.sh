#!/usr/bin/env bash
set -euo pipefail

compose_file="integrations/wordpress/choiceoye-erp-product-videos/tests/docker-compose.yml"
plugin_path="wp-content/plugins/choiceoye-erp-product-videos"

cleanup() {
  docker compose -f "$compose_file" down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose -f "$compose_file" up -d database wpcli
docker compose -f "$compose_file" exec -T wpcli wp core download --version=6.4.7 --force --allow-root
docker compose -f "$compose_file" exec -T wpcli wp config create \
  --dbname=wordpress --dbuser=wordpress --dbpass=wordpress --dbhost=database:3306 \
  --skip-check --force --allow-root
docker compose -f "$compose_file" exec -T wpcli wp core install \
  --url=http://wordpress.test --title='ChoiceOye Plugin Test' --admin_user=admin \
  --admin_password=admin-password --admin_email=admin@example.test --skip-email --allow-root
docker compose -f "$compose_file" exec -T wpcli wp plugin install woocommerce --version=8.5.0 --activate --allow-root
docker compose -f "$compose_file" exec -T wpcli wp plugin activate choiceoye-erp-product-videos --allow-root
docker compose -f "$compose_file" exec -T wpcli wp eval-file "$plugin_path/tests/integration.php" --allow-root
