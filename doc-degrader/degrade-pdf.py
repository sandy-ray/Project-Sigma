from config import imgconfig, pathsconfig
import augly.image as imaugs
# import fitz  # PyMuPDF
import pymupdf
from PIL import Image
import random
import io
import os


# Function to get a random value from a specified range using uniform distribution
def get_random_from_range(min_value, max_value):
	return random.uniform(min_value, max_value)

def random_degradation_config():
	degradation_config = {}

	degradation_config['scaling_factor'] = get_random_from_range(*imgconfig.scaling_factor_range)

	degradation_config['brightness_factor'] = get_random_from_range(*imgconfig.brightness_factor_range)

	degradation_config['rotation_degrees'] = get_random_from_range(*imgconfig.rotation_degree_range)

	degradation_config['blur_radius'] =	get_random_from_range(*imgconfig.blur_radius_range)

	degradation_config['pixelization_ratio'] = get_random_from_range(*imgconfig.pixelization_ratio_range)

	degradation_config['noise_mean'] = get_random_from_range(*imgconfig.noise_mean_range)
	degradation_config['noise_var'] = get_random_from_range(*imgconfig.noise_variance_range)

	degradation_config['stripe_line_width'] = get_random_from_range(*imgconfig.stripe_line_width_range)
	degradation_config['stripe_line_angle'] = get_random_from_range(*imgconfig.stripe_line_angle_range)
	degradation_config['stripe_line_density'] = get_random_from_range(*imgconfig.stripe_line_density_range)
	degradation_config['stripe_line_darkness'] = int(get_random_from_range(*imgconfig.stripe_line_darkness_range))
	degradation_config['stripe_line_opacity'] = get_random_from_range(*imgconfig.stripe_line_opacity_range)

	degradation_config['aspect_ratio'] = get_random_from_range(*imgconfig.aspect_ratio_range)

	degradation_config['contrast_factor'] = get_random_from_range(*imgconfig.contrast_factor_range)

	return degradation_config

def augment_image(image, degradation_config):
	# Scaling the image
	image = imaugs.scale(image, factor=degradation_config['scaling_factor'])

	# Adjusting Brightness
	image = imaugs.brightness(image, factor=degradation_config['brightness_factor'])

	# Apply Rotation
	image = imaugs.rotate(image, output_path=None, degrees=degradation_config['rotation_degrees'])

	# Apply Blur
	image = imaugs.blur(image, radius=degradation_config['blur_radius'])

	# Pixelization
	image = imaugs.pixelization(image, ratio=degradation_config['pixelization_ratio'])

	# Add Noise
	image = imaugs.random_noise(image, mean=degradation_config['noise_mean'], var=degradation_config['noise_var'], seed=42)

	# Overlay Stripes
	image = imaugs.overlay_stripes(image, 
		line_width=degradation_config['stripe_line_width'], 
		line_color=(degradation_config['stripe_line_darkness'], degradation_config['stripe_line_darkness'], degradation_config['stripe_line_darkness']), 
		line_angle=degradation_config['stripe_line_angle'], 
		line_density=degradation_config['stripe_line_density'], 
		line_type='solid', 
		line_opacity=degradation_config['stripe_line_opacity']
		)

	# Aspect Ratio
	image = imaugs.change_aspect_ratio(image, ratio=degradation_config['aspect_ratio'])

	# Contrast
	image = imaugs.contrast(image, factor=degradation_config['contrast_factor'])

	# Grayscale - the document is black and white, so any noise added will get converted to gray
	image = imaugs.grayscale(image, mode='luminosity')

	return image


def process_pdf_files(input_folder, output_folder, degradation_config):
	# Get list of PDF files in the input folder
	pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]

	for pdf_file in pdf_files:

		# open the input file
		inpdfdoc = pymupdf.open(os.path.join(input_folder,pdf_file))

		# Create a new PDF document to save the augmented pages
		outpdfdoc = pymupdf.open()

		for i, page in enumerate(inpdfdoc):

			# Render page to a pixmap (image)
			pix = page.get_pixmap(dpi=120)  # Adjust DPI as needed for quality

			# Convert pixmap to PIL Image
			img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

			# Apply augmentations using AugLy
			img = augment_image(img, degradation_config)

			# Convert PIL image to a byte stream (PNG or JPEG)
			img_byte_arr = io.BytesIO()
			img.save(img_byte_arr, format='PNG')
			img_bytes = img_byte_arr.getvalue()

			# Create a new page with the image's dimensions
			# Note: fitz uses points (1/72 inch). 
			page = outpdfdoc.new_page(width=img.width, height=img.height)

			# Insert the image onto the page
			# page.rect covers the entire page area
			page.insert_image(page.rect, stream=img_bytes)

		# Close the input file
		inpdfdoc.close()

		# Save the PDF
		outpdfdoc.save(os.path.join(output_folder,pdf_file))
		outpdfdoc.close()
		print(f"Processed {pdf_file}.")

def main():
	degradation_config = random_degradation_config()
	process_pdf_files(pathsconfig.input_pdf_folder, pathsconfig.output_pdf_folder, degradation_config)


if __name__ == "__main__":
	main()