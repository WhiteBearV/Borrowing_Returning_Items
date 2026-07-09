-- เปลี่ยนรายการนอกทะเบียนเป็นวัสดุสิ้นเปลือง (เก็บเลข code เดิมไว้)
-- gen โดย scripts/group_material.py — ตรวจ Report/จัดกลุ่มวัสดุ.md ก่อนรัน
-- กลุ่มพักไว้ (สว่าน/Cisco/Apple TV/webcam/จอ27/AP) ไม่แตะ ยังเป็น durable
BEGIN;
UPDATE equipment SET item_type = 'consumable'
WHERE name IN (
    'Cucumber RIS',
    'เครื่องคิดเลข F-789SGA',
    'Arduino-UNO-R3',
    'Converter USB 3.0 TO LAN TP-LINK',
    'Raspberry Pi 5 Ram 8',
    'IoT Activity kit Blynk Version',
    'Rasberry Pi 5 Ram 16',
    'ชุดการเรียนรู้วงจรไฟฟ้าเบื้องต้น',
    'Rasberry Pi 4 Computer Model B 4GB RAM',
    'M5 - Watch StickC Plus',
    'Arduino UNO R4 Minima',
    'Arduino Mega 2560 Rev3',
    'Hako Presto หัวแล้ง',
    'hako แท่นวาง',
    'Hako DS01 (ที่ดูดตะกั่ว)',
    'Traffic Light Control Module',
    'VENTION VGA to Hdmi',
    'TRANSCEND_CARD READER EXTERNAL',
    'UGREEN DisplayPort DP Male to HDMI Female',
    'Node32 Lite',
    'JETSON NANO Developer Kit + Adapter',
    'KidBright 32i',
    '3D HDMI High Speed HDMI A Male to Male Cable',
    'STEPING MOTOR DRIVER',
    'M5 StickC',
    'UGREEN HDMI TO VGA Converter',
    'MIXING PROCES MODULE',
    'Jetson Nano Develop Kit + Adapter',
    'SkyhorseHigh Speed HDMI Cable',
    'KidBright 32iP Heart Rate Project Kit',
    'Portable M.2 ZTEC ZD622',
    'UGREEN 4K 30Hz 10 in 1 USB-C HUB',
    'Arduino Nano',
    'Beagle Bone Black',
    'STM32 Discovery kit Iot Node',
    '1X4 HDMI SPLITTER HDR',
    'Soldering paste',
    'ชุดปกรณ์วัดและทดสอบระยะฉนวนความต่อเนื่องและอุณหภูมิขั้นพื้นฐาน',
    'สายไฟ',
    'NEXIS HDMI Splitter 4 port EDID',
    'ตะกั่ว'
);
COMMIT;
