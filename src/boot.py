# import storage
# storage.remount("/", readonly = False)
# storage.getmount("/").label = "M4_CLOCK"
# storage.remount("/", readonly = False)

# import os
# fs_stat = os.statvfs('/')
# print("Disk size: {0}KB".format(fs_stat[0] * fs_stat[2] // 1024))
# print("Free space: {0}KB".format(fs_stat[0] * fs_stat[3] // 1024))
# for pin in dir(microcontroller.pin):
#     if isinstance(getattr(microcontroller.pin, pin), microcontroller.Pin):
#         print("".join(("microcontroller.pin.", pin, "\t")), end=" ")
#         for alias in dir(board):
#             if getattr(board, alias) is getattr(microcontroller.pin, pin):
#                 print("".join(("", "board.", alias)), end=" ")
#     print()
