# ChoiceOye ERP Product Videos for WooCommerce

`choiceoye-erp-product-videos` displays product videos managed by ChoiceOye ERP
on standard WooCommerce product pages. It is optional: product, image, stock,
and order synchronization continue to work when it is not installed.

## Install

1. Build the package from the ERP repository:

   ```powershell
   .\scripts\build_wordpress_plugin.ps1
   ```

2. In WordPress, go to **Plugins → Add New → Upload Plugin** and upload
   `release_builds/wordpress/choiceoye-erp-product-videos-1.0.0.zip`.
3. Activate **ChoiceOye ERP Product Videos**. The site needs WordPress 6.4+,
   WooCommerce 8.5+, and PHP 8.0+.
4. In the ERP WooCommerce settings, enter a WordPress integration username and
   an [application password](https://wordpress.org/documentation/article/application-passwords/)
   when ERP-uploaded MP4 files must be copied to the WordPress Media Library.
5. Select **Test Connection** in the ERP. The result reports plugin detection,
   version compatibility, and the WordPress upload limit.

Do not use the WordPress product editor to change the video manifest. The
plugin's panel is deliberately read-only; ChoiceOye ERP is the sole editor.

## What synchronizes

Products can contain up to ten ordered videos. The ERP accepts HTTPS direct
MP4 links, supported YouTube links, supported Vimeo links, and local MP4
uploads up to 100 MB.

- YouTube, Vimeo, and direct-MP4 URLs remain external.
- ERP-uploaded MP4 files are streamed to WordPress Media Library only when a
  product video sync runs. The effective limit is the lower of ERP's 100 MB
  limit and the WordPress size reported by the plugin.
- The ERP sends the current ordered manifest in the product metadata key
  `choiceoye_erp_product_videos`; it does not use WooCommerce's `images`
  field.
- Videos appear after the native product images. YouTube uses a YouTube
  thumbnail; Vimeo and MP4 use the plugin's branded play tile. Selecting a
  tile opens a keyboard-accessible, non-autoplay lightbox.
- Removing a video clears its storefront association on the next successful
  video sync. WordPress Media Library files are intentionally retained.

The plugin supplies a section below the product summary when a theme does not
run the standard WooCommerce gallery thumbnail hook.

## Troubleshooting

- **Plugin not detected**: activate the plugin and confirm
  `/wp-json/choiceoye-erp/v1/status` responds on the store. This is a warning,
  not a reason to stop normal WooCommerce synchronization.
- **MP4 upload rejected**: reduce the file below the shown WordPress limit or
  raise WordPress/PHP upload limits, then retest the connector.
- **Video push pending or failed**: check the ERP WooCommerce status for the
  last video error. A video push waits until the ERP product has a mapped
  WooCommerce product.
- **File removed in ERP but remains in Media Library**: this is expected. The
  ERP removes only the product association and never automatically deletes
  WordPress attachments.

Deactivating or uninstalling the plugin also preserves the synchronized product
metadata and Media Library files.
