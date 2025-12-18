from app.models import User, Equipment, Booking, UsageLog, HomePageConfig, Lab, UserRole, EquipmentStatus
from datetime import datetime

# --- MOCK DATA STORE (Singleton Pattern for In-Memory Database) ---

BRAND_LOGO_URL = 'https://upload.wikimedia.org/wikipedia/vi/2/25/Logo_%C4%90%E1%BA%A1i_h%E1%BB%8Dc_Y_D%C6%B0%E1%BB%A3c_C%E1%BA%A7n_Th%C6%A1.png'

class DataStore:
    def __init__(self):
        self.users: list[User] = [
            User(id='adminctump', name='Quản Trị Viên Hệ Thống', email='tmthiet@ctump.edu.vn', phone='0909.123.456', role=UserRole.ADMIN, department='Khoa Cơ Bản', violationCount=0, isLocked=False, password='adminctump'),
            User(id='u2', name='Trần Thị Nhân Viên', email='nhanvien@ctump.edu.vn', phone='0912.333.444', role=UserRole.STAFF, department='Phòng Lab Hóa', violationCount=0, isLocked=False, password='123@'),
            User(id='u3', name='Lê Văn Sinh Viên', email='sinhvien@ctump.edu.vn', role=UserRole.STUDENT, department='Lớp KTPM', violationCount=0, isLocked=False, password='123@')
        ]
        
        self.equipment: list[Equipment] = [
            Equipment(
                id='e1', name='Kính Hiển Vi Điện Tử Olympus CX23', code='KHV-001', unit='Cái', origin='Nhật Bản', quantity=1,
                yearOfUse=2021, depreciation='10%', receiver='Nguyễn Văn A', usingDepartment='Bộ môn Sinh học',
                model='Olympus CX23', serial='SN-998877', provider='Thiết Bị Y Tế ABC', receiveDate='2021-01-15',
                price=15000000, managerId='adminctump', location='Lab 101', status=EquipmentStatus.AVAILABLE,
                images=['https://images.unsplash.com/photo-1582719508461-905c673771fd?auto=format&fit=crop&q=80&w=320'],
                notes='Kính hiển vi độ phân giải cao.'
            ),
            Equipment(
                id='e2', name='Máy Ly Tâm Lạnh Hettich', code='MLT-002', unit='Chiếc', origin='Đức', quantity=1,
                yearOfUse=2022, price=45000000, managerId='u2', location='Lab 102', status=EquipmentStatus.MAINTENANCE,
                images=['https://images.unsplash.com/photo-1579154204601-01588f351e67?auto=format&fit=crop&q=80&w=320'],
                notes='Đang đợi thay chổi than.', receiveDate='2022-03-10'
            )
        ]
        
        self.bookings: list[Booking] = []
        self.logs: list[UsageLog] = []
        
        self.labs: list[Lab] = [
            Lab(
                id='l1', name='Phòng Thí Nghiệm Hóa Sinh', 
                description='Chuyên nghiên cứu về các hợp chất tự nhiên, phân tích định lượng.',
                detailContent='Trang bị máy sắc ký lỏng (HPLC), máy quang phổ UV-Vis.',
                images=['https://images.unsplash.com/photo-1532094349884-543bc11b234d?auto=format&fit=crop&q=80&w=600'],
                locationCode='Lab 101'
            )
        ]
        
        self.home_config = HomePageConfig(
            appName='QUẢN LÝ TB KHOA KHOA HỌC CƠ BẢN',
            logo=BRAND_LOGO_URL,
            heroTitle='KHOA KHOA HỌC CƠ BẢN',
            heroSubtitle='TRƯỜNG ĐẠI HỌC Y DƯỢC CẦN THƠ',
            introTitle='Giới thiệu chung',
            introContent='Khoa Khoa Học Cơ Bản là đơn vị nòng cốt trong việc giảng dạy các môn khoa học nền tảng...',
            featuredTitle='Trang thiết bị tiêu biểu',
            featuredEquipmentIds=['e1', 'e2'],
            labsTitle='Các Phòng Thí Nghiệm & Nghiên Cứu',
            visitorCount=15300
        )

    def get_user(self, user_id: str):
        return next((u for u in self.users if u.id == user_id), None)

    def get_equipment(self, eq_id: str):
        return next((e for e in self.equipment if e.id == eq_id), None)

db = DataStore()