#!/usr/bin/env python3

try:
    import numpy as np
    from PIL import Image

    import os
    from copy import deepcopy

    import config
    import file
    from model import InpaintNN
    from libs.utils import *
except ImportError as e:
    print("Error when importing libraries: ", e)
    print("Some Python libraries are missing. You can install all required libraries by running in the command line 'pip install -r requirements.txt' ")
    exit(1)

class Decensor:
    def __init__(self):
        args = config.get_args()
        self.is_mosaic = args.is_mosaic
        self.variations = args.variations
        self.mask_color = [args.mask_color_red/255.0, args.mask_color_green/255.0, args.mask_color_blue/255.0]
        self.decensor_input_path = args.decensor_input_path
        self.decensor_input_original_path = args.decensor_input_original_path
        self.decensor_output_path = args.decensor_output_path

        if not os.path.exists(self.decensor_output_path):
            os.makedirs(self.decensor_output_path)

    def find_mask(self, colored):
        mask = np.ones(colored.shape, np.uint8)
        i, j = np.where(np.all(colored[0] == self.mask_color, axis=-1))
        mask[0, i, j] = 0
        return mask

    def load_model(self):
        self.model = InpaintNN(bar_model_name = "./models/bar/Train_775000.meta",
                               bar_checkpoint_name = "./models/bar/",
                               mosaic_model_name = "./models/mosaic/Train_290000.meta",
                               mosaic_checkpoint_name = "./models/mosaic/",
                               is_mosaic=self.is_mosaic)
                                
    def decensor_all_images_in_folder(self):
        #load model once at beginning and reuse same model
        self.load_model()
        
        input_color_dir = self.decensor_input_path
        file_names = os.listdir(input_color_dir)

        input_dir = self.decensor_input_path
        output_dir = self.decensor_output_path

        # Change False to True before release --> file.check_file(input_dir, output_dir, True)
        file_names, self.files_removed = file.check_file(input_dir, output_dir, False)

        #convert all images into np arrays and put them in a list
        for file_name in file_names:
            color_file_path = os.path.join(input_color_dir, file_name)
            color_basename, color_ext = os.path.splitext(file_name)
            if os.path.isfile(color_file_path) and color_ext.casefold() == ".png":
                print("--------------------------------------------------------------------------")
                print("Decensoring the image {}".format(color_file_path))
                try :
                    colored_img = Image.open(color_file_path)
                except:
                    print("Cannot identify image file (" +str(color_file_path)+")")
                    self.files_removed.append((color_file_path,3))
                    # incase of abnormal file format change (ex : text.txt -> text.png)
                    continue

                #if we are doing a mosaic decensor
                if self.is_mosaic:
                    #get the original file that hasn't been colored
                    ori_dir = self.decensor_input_original_path
                    test_file_names = os.listdir(ori_dir)
                    #since the original image might not be a png, test multiple file formats
                    valid_formats = {".png", ".jpg", ".jpeg"}
                    for test_file_name in test_file_names:
                        test_basename, test_ext = os.path.splitext(test_file_name)
                        if (test_basename == color_basename) and (test_ext.casefold() in valid_formats):
                            ori_file_path = os.path.join(ori_dir, test_file_name)
                            ori_img = Image.open(ori_file_path)
                            # colored_img.show()
                            self.decensor_image_variations(ori_img, colored_img, file_name)
                            break
                    else: #for...else, i.e if the loop finished without encountering break
                        print("Corresponding original, uncolored image not found in {}".format(color_file_path))
                        print("Check if it exists and is in the PNG or JPG format.")
                #if we are doing a bar decensor
                else:
                    self.decensor_image_variations(colored_img, colored_img, file_name)
            else:
                print("--------------------------------------------------------------------------")
                print("Image can't be found: "+str(color_file_path))
        print("--------------------------------------------------------------------------")
        if self.files_removed is not None:
            file.error_messages(None, self.files_removed)
        print("\nDecensoring complete!")

    def decensor_image_variations(self, ori, colored, file_name=None):
        for i in range(self.variations):
            self.decensor_image_variation(ori, colored, i, file_name)

    #create different decensors of the same image by flipping the input image
    def apply_variant(self, image, variant_number):
        if variant_number == 0:
            return image
        elif variant_number == 1:
            return image.transpose(Image.FLIP_LEFT_RIGHT)
        elif variant_number == 2:
            return image.transpose(Image.FLIP_TOP_BOTTOM)
        else:
            return image.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.FLIP_TOP_BOTTOM)

    #decensors one image at a time
    #TODO: decensor all cropped parts of the same image in a batch (then i need input for colored an array of those images and make additional changes)
    def decensor_image_variation(self, ori, colored, variant_number, file_name):
        ori = self.apply_variant(ori, variant_number)
        colored = self.apply_variant(colored, variant_number)
        width, height = ori.size
        #save the alpha channel if the image has an alpha channel
        has_alpha = False
        if (ori.mode == "RGBA"):
            has_alpha = True
            alpha_channel = np.asarray(ori)[:,:,3]
            alpha_channel = np.expand_dims(alpha_channel, axis =-1)
            ori = ori.convert('RGB')

        ori_array = image_to_array(ori)
        ori_array = np.expand_dims(ori_array, axis = 0)

        if self.is_mosaic:
            #if mosaic decensor, mask is empty
            # mask = np.ones(ori_array.shape, np.uint8)
            # print(mask.shape)
            colored = colored.convert('RGB')
            color_array = image_to_array(colored)
            color_array = np.expand_dims(color_array, axis = 0)
            mask = self.find_mask(color_array)
            mask_reshaped = mask[0,:,:,:] * 255.0
            mask_img = Image.fromarray(mask_reshaped.astype('uint8'))
            # mask_img.show()

        else:
            mask = self.find_mask(ori_array)

        #colored image is only used for finding the regions
        regions = find_regions(colored.convert('RGB'), [v*255 for v in self.mask_color])
        print("Found {region_count} censored regions in this image!".format(region_count = len(regions)))

        if len(regions) == 0 and not self.is_mosaic:
            print("No green regions detected! Make sure you're using exactly the right color.")
            return

        output_img_array = ori_array[0].copy()

        for region_counter, region in enumerate(regions, 1):
            bounding_box = expand_bounding(ori, region, expand_factor=1.5)
            crop_img = ori.crop(bounding_box)
            # crop_img.show()
            #convert mask back to image
            mask_reshaped = mask[0,:,:,:] * 255.0
            mask_img = Image.fromarray(mask_reshaped.astype('uint8'))
            #resize the cropped images
            crop_img = crop_img.resize((256, 256))
            crop_img_array = image_to_array(crop_img)
            #resize the mask images
            mask_img = mask_img.crop(bounding_box)
            mask_img = mask_img.resize((256, 256))
            # mask_img.show()
            #convert mask_img back to array
            mask_array = image_to_array(mask_img)
            #the mask has been upscaled so there will be values not equal to 0 or 1

            # mask_array[mask_array > 0] = 1
            # crop_img_array[..., :-1][mask_array==0] = (0,0,0)

            if not self.is_mosaic:
                a, b = np.where(np.all(mask_array == 0, axis = -1))
                # print(a,b)
                # print(crop_img_array[a,b])
                # print(crop_img_array[a,b,0])
                # print(crop_img_array.shape)
                # print(type(crop_img_array[0,0]))
                crop_img_array[a,b,:] = 0.
            # temp = Image.fromarray((crop_img_array * 255.0).astype('uint8'))
            # temp.show()

            crop_img_array = np.expand_dims(crop_img_array, axis = 0)
            mask_array = np.expand_dims(mask_array, axis = 0)

            # print(np.amax(crop_img_array))
            # print(np.amax(mask_array))
            # print(np.amax(masked))

            # print(np.amin(crop_img_array))
            # print(np.amin(mask_array))
            # print(np.amin(masked))

            # print(mask_array)

            crop_img_array = crop_img_array * 2.0 - 1
            # mask_array = mask_array / 255.0

            # Run predictions for this batch of images
            pred_img_array = self.model.predict(crop_img_array, crop_img_array, mask_array)

            pred_img_array = np.squeeze(pred_img_array, axis = 0)
            pred_img_array = (255.0 * ((pred_img_array + 1.0) / 2.0)).astype(np.uint8)

            #scale prediction image back to original size
            bounding_width = bounding_box[2]-bounding_box[0]
            bounding_height = bounding_box[3]-bounding_box[1]
            #convert np array to image

            # print(bounding_width,bounding_height)
            # print(pred_img_array.shape)

            pred_img = Image.fromarray(pred_img_array.astype('uint8'))
            # pred_img.show()
            pred_img = pred_img.resize((bounding_width, bounding_height), resample = Image.BICUBIC)
            # pred_img.show()

            pred_img_array = image_to_array(pred_img)

            # print(pred_img_array.shape)
            pred_img_array = np.expand_dims(pred_img_array, axis = 0)

            # copy the decensored regions into the output image
            for i in range(len(ori_array)):
                for col in range(bounding_width):
                    for row in range(bounding_height):
                        bounding_width_index = col + bounding_box[0]
                        bounding_height_index = row + bounding_box[1]
                        if (bounding_width_index, bounding_height_index) in region:
                            output_img_array[bounding_height_index][bounding_width_index] = pred_img_array[i,:,:,:][row][col]
            print("{region_counter} out of {region_count} regions decensored.".format(region_counter=region_counter, region_count=len(regions)))

        output_img_array = output_img_array * 255.0

        #restore the alpha channel if the image had one
        if has_alpha:
            output_img_array = np.concatenate((output_img_array, alpha_channel), axis = 2)

        output_img = Image.fromarray(output_img_array.astype('uint8'))
        output_img = self.apply_variant(output_img, variant_number)

        if file_name != None:
            #save the decensored image
            base_name, ext = os.path.splitext(file_name)
            file_name = base_name + " " + str(variant_number) + ext
            save_path = os.path.join(self.decensor_output_path, file_name)
            output_img.save(save_path)

            print("Decensored image saved to {save_path}!".format(save_path=save_path))
            return
        else:
            print("Decensored image. Returning it.")
            return output_img

if __name__ == '__main__':
    decensor = Decensor()
    decensor.decensor_all_images_in_folder()
