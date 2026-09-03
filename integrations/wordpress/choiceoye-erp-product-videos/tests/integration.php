<?php
if ( ! defined( 'ABSPATH' ) ) {
	exit( 1 );
}

if ( ! class_exists( 'WooCommerce' ) || ! class_exists( 'ChoiceOye_ERP_Product_Videos' ) ) {
	fwrite( STDERR, "WooCommerce or ChoiceOye plugin is not active.\n" );
	exit( 1 );
}

$product_id = wp_insert_post(
	array(
		'post_title'  => 'ERP video integration test',
		'post_type'   => 'product',
		'post_status' => 'publish',
	)
);
if ( is_wp_error( $product_id ) || ! $product_id ) {
	fwrite( STDERR, "Could not create integration-test product.\n" );
	exit( 1 );
}

update_post_meta(
	$product_id,
	ChoiceOye_ERP_Product_Videos::META_KEY,
	array(
		'schema_version' => 1,
		'videos'         => array(
			array(
				'erp_video_id' => 'integration-youtube',
				'source_type'  => 'youtube',
				'url'          => 'https://www.youtube.com/watch?v=abc123XYZ',
				'name'         => 'Integration video',
				'sort_order'   => 0,
			),
		),
	)
);

global $product;
$product = wc_get_product( $product_id );
ob_start();
do_action( 'woocommerce_product_thumbnails' );
$gallery = ob_get_clean();
if ( false === strpos( $gallery, 'choiceoye-video-slide' ) || false === strpos( $gallery, 'youtube-nocookie.com' ) ) {
	fwrite( STDERR, "ERP video slide did not render through WooCommerce gallery hook.\n" );
	exit( 1 );
}

$request  = new WP_REST_Request( 'GET', '/choiceoye-erp/v1/status' );
$response = rest_do_request( $request );
$payload  = $response->get_data();
if ( 200 !== $response->get_status() || 'choiceoye-erp-product-videos' !== ( $payload['plugin'] ?? '' ) ) {
	fwrite( STDERR, "Plugin status endpoint did not return the expected response.\n" );
	exit( 1 );
}

echo "ChoiceOye WordPress/WooCommerce integration passed.\n";
