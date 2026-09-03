<?php
/**
 * Plugin Name: ChoiceOye ERP Product Videos
 * Description: Displays ERP-managed MP4, YouTube, and Vimeo videos in WooCommerce product galleries.
 * Version: 1.0.0
 * Requires at least: 6.4
 * Requires PHP: 8.0
 * WC requires at least: 8.5
 * Author: ChoiceOye
 * Text Domain: choiceoye-erp-product-videos
 */

defined( 'ABSPATH' ) || exit;

final class ChoiceOye_ERP_Product_Videos {
	public const VERSION = '1.0.0';
	public const META_KEY = 'choiceoye_erp_product_videos';
	public const SCHEMA_VERSION = 1;
	public const MAX_VIDEOS = 10;

	private static bool $gallery_rendered = false;

	public static function boot(): void {
		add_action( 'init', array( self::class, 'register_meta' ) );
		add_action( 'rest_api_init', array( self::class, 'register_status_route' ) );
		add_action( 'wp_enqueue_scripts', array( self::class, 'enqueue_assets' ) );
		add_action( 'woocommerce_product_thumbnails', array( self::class, 'render_gallery_slides' ), 99 );
		add_action( 'woocommerce_after_single_product_summary', array( self::class, 'render_fallback' ), 4 );
		add_action( 'wp_footer', array( self::class, 'render_dialog' ) );
		add_action( 'add_meta_boxes_product', array( self::class, 'add_read_only_meta_box' ) );
		add_action( 'admin_notices', array( self::class, 'woocommerce_notice' ) );
	}

	private static function woocommerce_available(): bool {
		return class_exists( 'WooCommerce' )
			&& defined( 'WC_VERSION' )
			&& version_compare( WC_VERSION, '8.5', '>=' );
	}

	public static function register_meta(): void {
		register_post_meta(
			'product',
			self::META_KEY,
			array(
				'single'            => true,
				'type'              => 'object',
				'default'           => array( 'schema_version' => 1, 'videos' => array() ),
				'sanitize_callback' => array( self::class, 'sanitize_manifest' ),
				'auth_callback'     => static function (): bool {
					return current_user_can( 'edit_products' );
				},
				'show_in_rest'      => array(
					'schema' => array(
						'type'                 => 'object',
						'additionalProperties' => false,
						'properties'           => array(
							'schema_version' => array(
								'type' => 'integer',
								'enum' => array( self::SCHEMA_VERSION ),
							),
							'videos'         => array(
								'type'     => 'array',
								'maxItems' => self::MAX_VIDEOS,
								'items'    => array(
									'type'                 => 'object',
									'additionalProperties' => false,
									'required'             => array(
										'erp_video_id',
										'source_type',
										'url',
										'name',
										'sort_order',
									),
									'properties'           => array(
										'erp_video_id' => array(
											'type'      => 'string',
											'minLength' => 1,
											'maxLength' => 36,
										),
										'source_type'  => array(
											'type' => 'string',
											'enum' => array( 'mp4', 'uploaded', 'youtube', 'vimeo' ),
										),
										'url'          => array( 'type' => 'string', 'format' => 'uri' ),
										'name'         => array( 'type' => 'string', 'maxLength' => 255 ),
										'sort_order'   => array( 'type' => 'integer', 'minimum' => 0 ),
										'attachment_id' => array( 'type' => 'integer', 'minimum' => 1 ),
									),
								),
							),
						),
						'required'             => array( 'schema_version', 'videos' ),
					),
				),
			)
		);
	}

	public static function register_status_route(): void {
		register_rest_route(
			'choiceoye-erp/v1',
			'/status',
			array(
				'methods'             => 'GET',
				'permission_callback' => '__return_true',
				'callback'            => static function (): WP_REST_Response {
					return new WP_REST_Response(
						array(
							'plugin'           => 'choiceoye-erp-product-videos',
							'version'          => self::VERSION,
							'schema_versions'  => array( self::SCHEMA_VERSION ),
							'woocommerce'      => self::woocommerce_available(),
							'max_upload_bytes' => wp_max_upload_size(),
						)
					);
				},
			)
		);
	}

	public static function sanitize_manifest( mixed $value ): array {
		if ( is_string( $value ) ) {
			$decoded = json_decode( $value, true );
			$value   = is_array( $decoded ) ? $decoded : array();
		}
		if ( ! is_array( $value ) || (int) ( $value['schema_version'] ?? 0 ) !== self::SCHEMA_VERSION ) {
			return array( 'schema_version' => self::SCHEMA_VERSION, 'videos' => array() );
		}

		$clean = array();
		$rows  = is_array( $value['videos'] ?? null ) ? $value['videos'] : array();
		foreach ( array_slice( $rows, 0, self::MAX_VIDEOS ) as $row ) {
			$video = self::sanitize_video( $row );
			if ( null !== $video ) {
				$clean[] = $video;
			}
		}
		usort(
			$clean,
			static fn( array $left, array $right ): int => $left['sort_order'] <=> $right['sort_order']
		);
		foreach ( $clean as $index => &$video ) {
			$video['sort_order'] = $index;
		}
		unset( $video );
		return array( 'schema_version' => self::SCHEMA_VERSION, 'videos' => $clean );
	}

	private static function sanitize_video( mixed $row ): ?array {
		if ( ! is_array( $row ) ) {
			return null;
		}
		$source = sanitize_key( (string) ( $row['source_type'] ?? '' ) );
		$url    = esc_url_raw( (string) ( $row['url'] ?? '' ), array( 'https' ) );
		$id     = sanitize_text_field( (string) ( $row['erp_video_id'] ?? '' ) );
		if ( '' === $id || strlen( $id ) > 36 ) {
			return null;
		}
		$attachment_id = absint( $row['attachment_id'] ?? 0 );
		$name          = sanitize_text_field( (string) ( $row['name'] ?? '' ) );
		$name          = function_exists( 'mb_substr' ) ? mb_substr( $name, 0, 255 ) : substr( $name, 0, 255 );
		if ( 'uploaded' === $source ) {
			if ( $attachment_id < 1 || 'video/mp4' !== get_post_mime_type( $attachment_id ) ) {
				return null;
			}
			$attachment_url = wp_get_attachment_url( $attachment_id );
			if ( ! is_string( $attachment_url ) || ! str_starts_with( $attachment_url, 'https://' ) ) {
				return null;
			}
			$url = $attachment_url;
		}
		if ( ! self::valid_source_url( $source, $url ) ) {
			return null;
		}
		$clean = array(
			'erp_video_id' => $id,
			'source_type'  => $source,
			'url'          => $url,
			'name'         => $name,
			'sort_order'   => max( 0, (int) ( $row['sort_order'] ?? 0 ) ),
		);
		if ( $attachment_id ) {
			$clean['attachment_id'] = $attachment_id;
		}
		return $clean;
	}

	private static function valid_source_url( string $source, string $url ): bool {
		if ( ! str_starts_with( $url, 'https://' ) ) {
			return false;
		}
		$path = strtolower( (string) wp_parse_url( $url, PHP_URL_PATH ) );
		if ( in_array( $source, array( 'mp4', 'uploaded' ), true ) ) {
			return str_ends_with( $path, '.mp4' );
		}
		if ( 'youtube' === $source ) {
			return null !== self::youtube_id( $url );
		}
		if ( 'vimeo' === $source ) {
			return null !== self::vimeo_id( $url );
		}
		return false;
	}

	private static function youtube_id( string $url ): ?string {
		$host = strtolower( (string) wp_parse_url( $url, PHP_URL_HOST ) );
		$path = trim( (string) wp_parse_url( $url, PHP_URL_PATH ), '/' );
		if ( 'youtu.be' === $host && preg_match( '/^[A-Za-z0-9_-]{6,}$/', $path ) ) {
			return $path;
		}
		if ( ! in_array( $host, array( 'youtube.com', 'www.youtube.com', 'm.youtube.com' ), true ) ) {
			return null;
		}
		parse_str( (string) wp_parse_url( $url, PHP_URL_QUERY ), $query );
		if ( preg_match( '/^[A-Za-z0-9_-]{6,}$/', (string) ( $query['v'] ?? '' ) ) ) {
			return (string) $query['v'];
		}
		if ( preg_match( '#^(?:embed|shorts|live)/([A-Za-z0-9_-]{6,})$#', $path, $match ) ) {
			return $match[1];
		}
		return null;
	}

	private static function vimeo_id( string $url ): ?string {
		$host = strtolower( (string) wp_parse_url( $url, PHP_URL_HOST ) );
		if ( ! in_array( $host, array( 'vimeo.com', 'www.vimeo.com', 'player.vimeo.com' ), true ) ) {
			return null;
		}
		$parts = array_values( array_filter( explode( '/', (string) wp_parse_url( $url, PHP_URL_PATH ) ) ) );
		foreach ( $parts as $part ) {
			if ( ctype_digit( $part ) ) {
				return $part;
			}
		}
		return null;
	}

	private static function vimeo_player_url( string $url ): string {
		$id     = self::vimeo_id( $url );
		$player = 'https://player.vimeo.com/video/' . rawurlencode( (string) $id );
		$parts  = array_values( array_filter( explode( '/', (string) wp_parse_url( $url, PHP_URL_PATH ) ) ) );
		if ( 2 === count( $parts ) && ctype_digit( $parts[0] ) && preg_match( '/^[A-Za-z0-9]+$/', $parts[1] ) ) {
			$player .= '?h=' . rawurlencode( $parts[1] );
		}
		return $player;
	}

	private static function videos_for_product( int $product_id ): array {
		if ( 'publish' !== get_post_status( $product_id ) ) {
			return array();
		}
		$manifest = self::sanitize_manifest( get_post_meta( $product_id, self::META_KEY, true ) );
		return $manifest['videos'];
	}

	private static function current_videos(): array {
		global $product;
		return self::woocommerce_available() && $product instanceof WC_Product
			? self::videos_for_product( $product->get_id() )
			: array();
	}

	public static function enqueue_assets(): void {
		if ( ! function_exists( 'is_product' ) || ! is_product() || array() === self::current_videos() ) {
			return;
		}
		wp_enqueue_style(
			'choiceoye-erp-product-videos',
			plugins_url( 'assets/product-videos.css', __FILE__ ),
			array(),
			self::VERSION
		);
		wp_enqueue_script(
			'choiceoye-erp-product-videos',
			plugins_url( 'assets/product-videos.js', __FILE__ ),
			array(),
			self::VERSION,
			true
		);
	}

	private static function presentation( array $video ): array {
		$source = $video['source_type'];
		$url    = $video['url'];
		if ( 'youtube' === $source ) {
			$id = self::youtube_id( $url );
			return array(
				'thumbnail' => 'https://i.ytimg.com/vi/' . rawurlencode( (string) $id ) . '/hqdefault.jpg',
				'player'    => 'https://www.youtube-nocookie.com/embed/' . rawurlencode( (string) $id ) . '?rel=0',
			);
		}
		if ( 'vimeo' === $source ) {
			return array(
				'thumbnail' => plugins_url( 'assets/video-placeholder.svg', __FILE__ ),
				'player'    => self::vimeo_player_url( $url ),
			);
		}
		return array(
			'thumbnail' => plugins_url( 'assets/video-placeholder.svg', __FILE__ ),
			'player'    => $url,
		);
	}

	private static function render_button( array $video, string $class ): void {
		$view  = self::presentation( $video );
		$label = '' !== $video['name'] ? $video['name'] : __( 'Product video', 'choiceoye-erp-product-videos' );
		printf(
			'<button type="button" class="%1$s" data-choiceoye-video data-source="%2$s" data-player-url="%3$s" aria-label="%4$s"><img src="%5$s" alt="" loading="lazy"><span aria-hidden="true" class="choiceoye-video-play">&#9654;</span><span class="choiceoye-video-name">%6$s</span></button>',
			esc_attr( $class ),
			esc_attr( $video['source_type'] ),
			esc_url( $view['player'] ),
			esc_attr( sprintf( __( 'Play %s', 'choiceoye-erp-product-videos' ), $label ) ),
			esc_url( $view['thumbnail'] ),
			esc_html( $label )
		);
	}

	public static function render_gallery_slides(): void {
		$videos = self::current_videos();
		if ( array() === $videos ) {
			return;
		}
		self::$gallery_rendered = true;
		foreach ( $videos as $video ) {
			$view = self::presentation( $video );
			echo '<div class="woocommerce-product-gallery__image choiceoye-video-slide" data-thumb="' . esc_url( $view['thumbnail'] ) . '" data-thumb-alt="' . esc_attr__( 'Video', 'choiceoye-erp-product-videos' ) . '">';
			self::render_button( $video, 'choiceoye-video-trigger choiceoye-video-trigger--gallery' );
			echo '</div>';
		}
	}

	public static function render_fallback(): void {
		$videos = self::current_videos();
		if ( self::$gallery_rendered || array() === $videos ) {
			return;
		}
		echo '<section class="choiceoye-video-fallback" aria-labelledby="choiceoye-video-heading"><h2 id="choiceoye-video-heading">' . esc_html__( 'Product videos', 'choiceoye-erp-product-videos' ) . '</h2><div class="choiceoye-video-grid">';
		foreach ( $videos as $video ) {
			self::render_button( $video, 'choiceoye-video-trigger' );
		}
		echo '</div></section>';
	}

	public static function render_dialog(): void {
		if ( array() === self::current_videos() ) {
			return;
		}
		echo '<div class="choiceoye-video-dialog" data-choiceoye-dialog hidden><div class="choiceoye-video-backdrop" data-choiceoye-close></div><div class="choiceoye-video-dialog-panel" role="dialog" aria-modal="true" aria-labelledby="choiceoye-video-dialog-title"><h2 id="choiceoye-video-dialog-title" class="screen-reader-text">' . esc_html__( 'Product video', 'choiceoye-erp-product-videos' ) . '</h2><button type="button" class="choiceoye-video-close" data-choiceoye-close aria-label="' . esc_attr__( 'Close video', 'choiceoye-erp-product-videos' ) . '">&times;</button><div class="choiceoye-video-player" data-choiceoye-player></div></div></div>';
	}

	public static function add_read_only_meta_box(): void {
		add_meta_box(
			'choiceoye-erp-product-videos',
			__( 'ChoiceOye ERP Product Videos', 'choiceoye-erp-product-videos' ),
			array( self::class, 'render_meta_box' ),
			'product',
			'side',
			'default'
		);
	}

	public static function render_meta_box( WP_Post $post ): void {
		$manifest = self::sanitize_manifest( get_post_meta( $post->ID, self::META_KEY, true ) );
		$videos   = $manifest['videos'];
		echo '<p>' . esc_html__( 'Managed by ChoiceOye ERP. Edit and reorder videos in the ERP.', 'choiceoye-erp-product-videos' ) . '</p>';
		echo '<p><strong>' . esc_html( sprintf( _n( '%d synchronized video', '%d synchronized videos', count( $videos ), 'choiceoye-erp-product-videos' ), count( $videos ) ) ) . '</strong></p>';
		if ( $videos ) {
			echo '<ol>';
			foreach ( $videos as $video ) {
				echo '<li>' . esc_html( $video['name'] ?: strtoupper( $video['source_type'] ) ) . '</li>';
			}
			echo '</ol>';
		}
	}

	public static function woocommerce_notice(): void {
		if ( current_user_can( 'activate_plugins' ) && ! self::woocommerce_available() ) {
			echo '<div class="notice notice-warning"><p>' . esc_html__( 'ChoiceOye ERP Product Videos requires WooCommerce 8.5 or newer.', 'choiceoye-erp-product-videos' ) . '</p></div>';
		}
	}
}

ChoiceOye_ERP_Product_Videos::boot();
