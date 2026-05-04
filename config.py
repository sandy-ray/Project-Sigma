##
## Configuration file for image degradation parameters
##

# Image degradation configuration
imgconfig = type('Config', (), {})()

## Scale the image
# keeping scaling to 1.0 for now
imgconfig.scaling_factor_range = (1.0, 1.0)  # Scaling factor range for image augmentation

## Change brightness
# values less than 1.0 darken the image and values greater than 1.0 brighten the image.
# Setting factor to 1.0 will not alter the image’s brightness
imgconfig.brightness_factor_range = (0.7, 1.3)  # Brightness adjustment factor range

## Change contrast in the image
imgconfig.contrast_factor_range = (0.5, 0.9)  # Contrast adjustment factor range

## Rotate the image
# the amount of degrees that the original image will be rotated counter clockwise
imgconfig.rotation_degree_range = (-3.0, 3.0)  # Rotation degree range

## Blur the image
# the larger the radius, the blurrier the image (tried 0.5 to 1.5)
imgconfig.blur_radius_range = (0.2, 0.5)  # Blur radius range

## Pixelate the image
# smaller values result in a more pixelated image, 1.0 indicates no change, 
# and any value above one doesn’t have a noticeable effect
imgconfig.pixelization_ratio_range = (0.65, 0.75)  # Pixelization ratio range (lower means more pixelation)

## Add gaussian noise
# mean (float) – mean of the gaussian noise added
# var (float) – variance of the gaussian noise added
imgconfig.noise_mean_range = (0.0, 0.0)  # Mean for random noise (fixed at 0.0 for Gaussian noise)
imgconfig.noise_variance_range = (0.005, 0.02)  # Variance range for random noise

## Add stripes (just another artifact to degrade the image)
# line_width (float) – the width of individual stripes as a float value ranging from 0 to 1. Defaults to 0.5
# line_angle (float) – the angle of the stripes in degrees, ranging from -360° to 360°. Defaults to 0° or horizontal stripes
# line_density (float) – controls the distance between stripes represented as a float value ranging from 0 to 1, with 1 indicating more densely spaced stripes. Defaults to 0.5
# line_color/darkness (Tuple[int, int, int]) – color of the overlaid stripes in RGB values
# line_opacity (float) – the opacity of the stripes, ranging from 0 to 1 with 1 being opaque. Defaults to 1.0
imgconfig.stripe_line_width_range = (0.25, 1.0)  # Line width range for overlay stripes
imgconfig.stripe_line_angle_range = (-45, 45)  # Line angle range for overlay stripes
imgconfig.stripe_line_density_range = (0.3, 0.7)  # Line density range for overlay stripes
imgconfig.stripe_line_darkness_range = (128, 200)  # Line darkness range for overlay stripes
imgconfig.stripe_line_opacity_range = (0.1, 0.5)  # Line opacity range for overlay stripes

## Change aspect ratio of the image
# ratio (float) – aspect ratio, i.e. width/height, of the new image
imgconfig.aspect_ratio_range = (0.72, 0.72)  # kept it fixed for now, = 0.72 for 11x8 page


##
## file paths and other constants
##
pathsconfig = type('Config',(),{})()
pathsconfig.input_pdf_folder = "input-files/"  # Path to the input PDF file
pathsconfig.output_pdf_folder = "output-files/"  # Path to save the augmented PDF files