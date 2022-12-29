import argparse
import os
from typing import Union

from loguru import logger
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch
from unipose.datasets.animal_kingdom import AnimalKingdomDataset
from unipose.datasets.coco import COCODataset
from unipose.datasets.mpii import MPIIDataset

from unipose.models import UniPose
from unipose.losses import GLES


def inference(image_path_or_tensor, model, /, device=torch.device("cpu")):
    model.eval()
    if isinstance(image_path_or_tensor, str):
        image = Image.open(image_path)
        image = image.resize((256, 256))
        image = np.array(image)
        # remove alpha channel
        if image.shape[2] == 4:
            image = image[:, :, :3]
        image = torch.from_numpy(image).float().div(255).permute(2, 0, 1).unsqueeze(0).to(device)
    elif isinstance(image_path_or_tensor, torch.Tensor):
        image = image_path_or_tensor.to(device)
    with torch.no_grad():
        output = model(image)
    return output


OUTPUT_SIZE = 1024
cwd = os.getcwd()
if os.path.basename(cwd) == "scripts":
    cwd = os.path.dirname(cwd)
    logger.warning("Running from scripts folder. Directories should be relative to {}", cwd)
def get_abs_path(dir_path: str, create_if_not_exists: bool = False):
    """Gets the absolute path of any path: relative or absolute."""
    if not os.path.isabs(dir_path):
        _path = os.path.join(cwd, dir_path)
        if create_if_not_exists:
            os.makedirs(_path, exist_ok=True)
        return _path
    else:
        if create_if_not_exists:
            os.makedirs(dir_path, exist_ok=True)
        return dir_path

@logger.catch
def draw_skel(src_image_path_or_arr: Union[str, np.ndarray], heatmaps: torch.Tensor, render_path: str):
    """Draws the skeleton on the image."""
    if isinstance(src_image_path_or_arr, str):
        base_image = Image.open(src_image_path_or_arr)
    elif isinstance(src_image_path_or_arr, np.ndarray):
        # If the shape is 4 (bz, 3, h, w), then take the first one and convert to (h, w, 3)
        if len(src_image_path_or_arr.shape) == 4:
            logger.debug("Shape has length 4, assuming (bz, 3, h, w). Taking the first one and converting to (h, w, 3).")
            src_image_path_or_arr = src_image_path_or_arr[0].transpose(1, 2, 0)
        # If all the values are between 0 and 1, then multiply by 255
        if np.max(src_image_path_or_arr) <= 1:
            logger.debug("All values are between 0 and 1. Multiplying by 255. (Assuming the image is normalized).")
            src_image_path_or_arr = src_image_path_or_arr * 255
        src_image_path_or_arr = src_image_path_or_arr.astype(np.uint8)
        try:
            base_image = Image.fromarray(src_image_path_or_arr)
        except Exception as e:
            logger.error("Could not convert the array to an image. Error: {}", e)
            raise e
    else:
        raise TypeError("src_image_path_or_arr must be either a string or a numpy array.")
    if base_image.mode != "RGB":
        base_image = base_image.convert("RGB")
    base_image = base_image.resize((OUTPUT_SIZE, OUTPUT_SIZE), resample=Image.Resampling.BICUBIC)
    # Generate output
    x = []
    y = []
    confidence = []
    base_image_draw = ImageDraw.Draw(base_image, "RGBA")

    # Color preset: e54bd6-59aff9-8fefb7-fc906c-ccbf0e
    draw_config = {
        "font": get_abs_path("docs/blanket.otf"),
        "colors": {
            "head": "#e54bd6",
            "arm_left": "#59aff9",
            "arm_right": "#8fefb7",
            "leg_left": "#fc906c",
            "leg_right": "#ccbf0e",
            "shadow": "#e54bd6",
            "border": "#ffffff"
        },
        "radius": 7,
        "line_width": 3,
        "caption": True
    }
    __radius = draw_config["radius"]
    __line_width = draw_config["line_width"]
    __caption = draw_config["caption"]
    __colors = draw_config["colors"]
    __font = ImageFont.truetype(draw_config["font"], 20) if os.path.exists(draw_config["font"]) else None
    for i in range(heatmaps.shape[1]):
        _image_arr = heatmaps[0, i, :, :].cpu().numpy()
        # _image_arr = (_image_arr - _image_arr.min()) / (_image_arr.max() - _image_arr.min())
        idx = np.argmax(_image_arr)
        x.append(idx % _image_arr.shape[0] * OUTPUT_SIZE // _image_arr.shape[1])
        y.append(idx // _image_arr.shape[0] * OUTPUT_SIZE // _image_arr.shape[0])
        confidence.append(np.max(_image_arr))
    if sum(x) == 0 and sum(y) == 0:
        logger.warning("No keypoints in heatmaps: All keypoints are (0, 0). Will not render skeleton.")
        
    # Draw lines between joints
    eps = 1e-6
    if (x[1] + y[1] > eps) and (x[2] + y[2] > eps):
        base_image_draw.line((x[1], y[1], x[2], y[2]), fill=__colors["arm_left"], width=__line_width)
    if (x[2] + y[2] > eps) and (x[3] + y[3] > eps):
        base_image_draw.line((x[2], y[2], x[3], y[3]), fill=__colors["arm_left"], width=__line_width)
    if (x[4] + y[4] > eps) and (x[5] + y[5] > eps) and (x[6] + y[6] > eps):
        base_image_draw.line((x[4], y[4], x[5], y[5]), fill=__colors["arm_right"], width=__line_width)
    if (x[5] + y[5] > eps) and (x[6] + y[6] > eps):
        base_image_draw.line((x[5], y[5], x[6], y[6]), fill=__colors["arm_right"], width=__line_width)
    if (x[7] + y[7] > eps) and (x[8] + y[8] > eps):
        base_image_draw.line((x[7], y[7], x[8], y[8]), fill=__colors["leg_left"], width=__line_width)
    if (x[8] + y[8] > eps) and (x[9] + y[9] > eps):
        base_image_draw.line((x[8], y[8], x[9], y[9]), fill=__colors["leg_left"], width=__line_width)
    if (x[10] + y[10] > eps) and (x[11] + y[11] > eps):
        base_image_draw.line((x[10], y[10], x[11], y[11]), fill=__colors["leg_right"], width=__line_width)
    if (x[11] + y[11] > eps) and (x[12] + y[12] > eps):
        base_image_draw.line((x[11], y[11], x[12], y[12]), fill=__colors["leg_right"], width=__line_width)

    # For each joint, draw a circle
    for i in range(13):
        if x[i] == 0 and y[i] == 0:
            continue
        if i in [0]:
            # Head
            base_image_draw.ellipse((x[i]-__radius, y[i]-__radius, x[i]+__radius, y[i]+__radius), fill=__colors["head"], outline=__colors["border"])
        elif i in [1, 2, 3]:
            # Left arm
            base_image_draw.ellipse((x[i]-__radius, y[i]-__radius, x[i]+__radius, y[i]+__radius), fill=__colors["arm_left"], outline=__colors["border"])
        elif i in [4, 5, 6]:
            # Right arm
            base_image_draw.ellipse((x[i]-__radius, y[i]-__radius, x[i]+__radius, y[i]+__radius), fill=__colors["arm_right"], outline=__colors["border"])
        elif i in [7, 8, 9]:
            # Left leg
            base_image_draw.ellipse((x[i]-__radius, y[i]-__radius, x[i]+__radius, y[i]+__radius), fill=__colors["leg_left"], outline=__colors["border"])
        elif i in [10, 11, 12]:
            # Right leg
            base_image_draw.ellipse((x[i]-__radius, y[i]-__radius, x[i]+__radius, y[i]+__radius), fill=__colors["leg_right"], outline=__colors["border"])
        if __caption:
            if x[i] < OUTPUT_SIZE - 160 and y[i] < OUTPUT_SIZE - 20:
                base_image_draw.text((x[i]+__radius, y[i]+__radius), "{:.2f}@{}".format(confidence[i], i), fill="white", font=__font, anchor="la")
            else:
                base_image_draw.text((x[i]-__radius, y[i]-__radius), "{:.2f}@{}".format(confidence[i], i), fill="white", font=__font, anchor="rs")

    # Draw shadow points (mid of point 1 and 4; mid of point 7 and 10)
    mid_1_x, mid_1_y = (x[1] + x[4]) // 2, (y[1] + y[4]) // 2
    mid_2_x, mid_2_y = (x[7] + x[10]) // 2, (y[7] + y[10]) // 2
    # TODO
    # base_image_draw.ellipse((mid_1_x-__radius, mid_1_y-__radius, mid_1_x+__radius, mid_1_y+__radius), fill=__colors["shadow"], outline=__colors["border"])
    render_path = get_abs_path(render_path)
    base_image.save(render_path)
    logger.info("Skeleton image saved to {}".format(render_path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image_path", type=str, help="Path to the image to be processed")
    parser.add_argument("--dataset", type=str, help="Sample from a dataset. Options: 'coco', 'mpii', 'animal_kingdom'")
    parser.add_argument("--dataset_path", type=str, help="Path to the dataset. Required if --dataset is specified")
    parser.add_argument("--checkpoint", type=str, default="exp/model-latest.pth")
    parser.add_argument("--gpu", type=int, default=0, help="GPU ID. Set to -1 to use CPU")
    parser.add_argument("--image_size", type=int, default=256, help="Image size of input image.")
    parser.add_argument("--scale_factor", type=int, default=4, help="Patch size of output keypoint heatmaps. Must be 4 if Unipose is used without modification")
    parser.add_argument("--output_dir", type=str, default="exp/output_vis")
    args = parser.parse_args()

    output_dir = get_abs_path(args.output_dir, create_if_not_exists=True)

    # Exit if checkpoint not found
    # checkpoint_path = os.path.join(base_dir, args.checkpoint)
    checkpoint_path = get_abs_path(args.checkpoint)
    if not os.path.exists(checkpoint_path):
        logger.error("Checkpoint not found: {}".format(checkpoint_path))
        exit(1)

    # Exit if image not found
    if args.image_path is not None:
        image_path = get_abs_path(args.image_path)
        if not os.path.exists(image_path):
            logger.error("Image not found: {}".format(image_path))
            exit(1)
        mode = "image"
    elif args.dataset is not None:
        # Get random image from dataset
        if args.dataset == "coco":
            dataset_path = get_abs_path("datasets/coco") if args.dataset_path is None else get_abs_path(args.dataset_path)
            dataloader = COCODataset(dataset_path).make_dataloader(batch_size=1, shuffle=True)
        elif args.dataset == "mpii":
            dataset_path = get_abs_path("datasets/mpii") if args.dataset_path is None else get_abs_path(args.dataset_path)
            dataloader = MPIIDataset(dataset_path).make_dataloader(batch_size=1, shuffle=True)
        elif args.dataset == "animal_kingdom":
            dataset_path = get_abs_path("datasets/animal_kingdom") if args.dataset_path is None else get_abs_path(args.dataset_path)
            dataloader = AnimalKingdomDataset(dataset_path).make_dataloader(batch_size=1, shuffle=True)
        else:
            logger.error("Unknown dataset: {}".format(args.dataset))
            exit(1)
        mode = "dataset"

    # Set device
    if args.gpu == -1:
        device = torch.device("cpu")
    else:
        device = torch.device("cuda:{}".format(args.gpu) if torch.cuda.is_available() else "cpu")

    # Create model
    logger.debug("Creating model...")
    model = UniPose(13, resnet_layers=[3, 8, 36, 3])
    model = model.to(device)
    logger.info("Loading checkpoint from {}...", checkpoint_path)
    model.load_state_dict(torch.load(checkpoint_path, map_location=device))
    
    # Copy source image to output directory
    if mode == "image":
        output_image_path = os.path.join(output_dir, os.path.basename(image_path))
        import shutil
        try:
            shutil.copyfile(image_path, output_image_path)
            logger.info("Copied source image to {}", output_image_path)
        except Exception as e:
            logger.warning("Cannot copy source image to {}", output_image_path)
            logger.warning(e)
        image_path_or_tensor = image_path
    elif mode == "dataset":
        # Sample from a dataloader
        for batch in dataloader:
            image_tensor = batch["images"]
            image_array_src = image_tensor.cpu().detach().numpy()
            image_array = image_array_src[0].transpose(1, 2, 0) # (C, H, W) -> (H, W, C)
            # image_array = image_array[:, :, ::-1] # BGR -> RGB
            image_array = image_array * 255 # [0, 1] -> [0, 255]
            image_path = os.path.join(output_dir, "source.png")
            image = Image.fromarray(image_array.astype(np.uint8))
            image.save(image_path)
            logger.info("Saved source image to {}", image_path)
            kp_gt = batch["keypoint_images"]
            logger.debug("Drawing ground truth skeleton...")
            draw_skel(image_array_src, kp_gt, os.path.join(output_dir, "gt.png"))
            logger.info("Saved ground truth skeleton to {}", os.path.join(output_dir, "gt.png"))
            image_path_or_tensor = image_tensor
            break

    # Inference
    logger.info("Processing image...")
    ret = inference(image_path_or_tensor, model, device=device)
    
    # Render skeleton image
    skel_path = os.path.join(output_dir, "skel.png")
    draw_skel(image_path, ret, skel_path)
    
    