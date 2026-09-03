<?php
define( 'ABSPATH', __DIR__ );

function add_action() {}
function register_post_meta() {}
function register_rest_route() {}
function sanitize_key( $value ) { return strtolower( preg_replace( '/[^a-z0-9_-]/i', '', $value ) ); }
function esc_url_raw( $value ) { return filter_var( $value, FILTER_VALIDATE_URL ) ? $value : ''; }
function sanitize_text_field( $value ) { return trim( strip_tags( $value ) ); }
function absint( $value ) { return abs( (int) $value ); }
function get_post_mime_type( $id ) { return 91 === $id ? 'video/mp4' : ''; }
function wp_get_attachment_url( $id ) { return 91 === $id ? 'https://shop.test/demo.mp4' : false; }
function wp_parse_url( $url, $component = -1 ) { return parse_url( $url, $component ); }

require dirname( __DIR__ ) . '/choiceoye-erp-product-videos.php';

function verify( $condition, $message ) {
	if ( ! $condition ) {
		fwrite( STDERR, $message . PHP_EOL );
		exit( 1 );
	}
}

$manifest = ChoiceOye_ERP_Product_Videos::sanitize_manifest(
	array(
		'schema_version' => 1,
		'videos' => array(
			array(
				'erp_video_id' => 'video-two',
				'source_type' => 'vimeo',
				'url' => 'https://vimeo.com/channels/demo/1234567',
				'name' => 'Second',
				'sort_order' => 4,
			),
			array(
				'erp_video_id' => 'video-one',
				'source_type' => 'youtube',
				'url' => 'https://www.youtube.com/watch?v=abc123XYZ',
				'name' => '<b>First</b>',
				'sort_order' => 0,
			),
			array(
				'erp_video_id' => 'bad',
				'source_type' => 'youtube',
				'url' => 'https://example.test/not-video',
				'sort_order' => 1,
			),
		)
	)
);

verify( 2 === count( $manifest['videos'] ), 'Invalid providers must be discarded.' );
verify( 'video-one' === $manifest['videos'][0]['erp_video_id'], 'Videos must be sorted.' );
verify( 'First' === $manifest['videos'][0]['name'], 'Names must be plain text.' );
verify( 1 === $manifest['videos'][1]['sort_order'], 'Sort order must be normalized.' );

$uploaded = ChoiceOye_ERP_Product_Videos::sanitize_manifest(
	array(
		'schema_version' => 1,
		'videos' => array(
			array(
				'erp_video_id' => 'uploaded-one',
				'source_type' => 'uploaded',
				'url' => 'https://old.test/demo.mp4',
				'attachment_id' => 91,
			)
		)
	)
);
verify( 'https://shop.test/demo.mp4' === $uploaded['videos'][0]['url'], 'Attachment URL wins.' );

$many = array();
for ( $index = 0; $index < 11; ++$index ) {
	$many[] = array(
		'erp_video_id' => 'video-' . $index,
		'source_type'  => 'mp4',
		'url'          => 'https://cdn.test/video-' . $index . '.mp4',
		'name'         => 'Video ' . $index,
		'sort_order'   => $index,
	);
}
$capped = ChoiceOye_ERP_Product_Videos::sanitize_manifest(
	array( 'schema_version' => 1, 'videos' => $many )
);
verify( 10 === count( $capped['videos'] ), 'Video manifests must be capped at ten entries.' );

echo "ChoiceOye WordPress plugin smoke passed." . PHP_EOL;
