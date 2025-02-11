import os
import subprocess

# Define a function to print clean bold messages
def print_bold(message):
    print(f"{message}")

# Define paths to your main video and directories
main_video = 'main.mov'  # Main video file
background_videos_dir = 'background'  # Directory containing your background videos
music_file = 'music/music.mp3'  # Path to your music file

# Define the output directory
output_dir = 'output_videos'
os.makedirs(output_dir, exist_ok=True)

# Set the desired duration for each output video
desired_duration = 10  # 8 seconds

# Fetch all video files from the background videos directory
background_videos = [os.path.join(background_videos_dir, vid) for vid in os.listdir(background_videos_dir) if vid.endswith('.mp4')]

# Check if there are background videos
if not background_videos:
    print_bold("No background videos found in the specified directory.")
    exit()

# Loop through each background video
for background_video in background_videos:
    # Get the total duration of the background video using ffprobe
    print_bold(f"Processing video: {os.path.basename(background_video)}...")
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', background_video], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    if result.returncode != 0:
        print_bold(f"Error fetching duration for {os.path.basename(background_video)}: {result.stdout}")
        continue

    total_duration = float(result.stdout)

    # Calculate how many 8-second chunks can be created from the background video
    num_segments = int(total_duration // desired_duration)
    print_bold(f"Video: {os.path.basename(background_video)} can produce up to {num_segments} videos of {desired_duration} seconds.")

    # Prompt the user to enter how many videos to create
    user_input = input(f"How many videos do you want to create from {os.path.basename(background_video)}? (Max: {num_segments}): ")

    # Ensure the input is valid
    try:
        num_videos_to_produce = min(int(user_input), num_segments)
    except ValueError:
        print_bold("Invalid input, skipping this video.")
        continue

    # Automatically generate videos based on user input without further prompts
    print_bold(f"Creating {num_videos_to_produce} video(s) from {os.path.basename(background_video)}...")

    for segment in range(num_videos_to_produce):
        start_time = segment * desired_duration
        output_video = os.path.join(output_dir, f'video_{segment + 1}.mp4')

        # Construct the ffmpeg command for each segment
        command = [
            'ffmpeg',
            '-stream_loop', '1',
            '-i', main_video,
            '-ss', str(start_time),
            '-t', str(desired_duration),
            '-i', background_video,

            '-filter_complex', (
                f'[0:v]trim=duration={desired_duration},setpts=N/FRAME_RATE/TB,format=rgba[main];'
                f'[1:v]trim=duration={desired_duration},crop=ih*9/16:ih,scale=1080:1920[bg];'
                '[bg][main]overlay=(W-w)/2:(H-h)/2:shortest=1[v]'
            ),
            '-map', '[v]',
            '-map', '2:a',
            '-i', music_file,
            '-t', str(desired_duration),
            '-c:v', 'libx264',
            '-b:v', '3500k',  # Adjust this bitrate as needed
            '-c:a', 'aac',
            '-strict', 'experimental',
            '-pix_fmt', 'yuv420p',
            output_video
        ]

        # Run the ffmpeg command and check for errors
        print_bold(f"Generating video segment {segment + 1}...")
        process = subprocess.run(command, capture_output=True, text=True)
        if process.returncode != 0:
            print_bold(f"Error generating video segment {segment + 1}: {process.stderr}")
        else:
            print_bold(f"Successfully created: {output_video}")

print_bold('Mixing complete. Check the output_videos directory.')
