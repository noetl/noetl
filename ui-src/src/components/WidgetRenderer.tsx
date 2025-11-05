import React from "react";
import {
  Card,
  Statistic,
  Table,
  Progress,
  List,
  Typography,
  Space,
} from "antd";
import { VisualizationWidget, TableColumn } from "../types";

const { Title, Text } = Typography;

interface WidgetRendererProps {
  widget: VisualizationWidget;
}

const WidgetRenderer: React.FC<WidgetRendererProps> = ({ widget }) => {
  const renderContent = () => {
    switch (widget.type) {
      case "metric":
        return (
          <Statistic
            title={widget.title}
            value={widget.data.value}
            precision={widget.config.format === "percentage" ? 2 : 0}
            suffix={widget.config.format === "percentage" ? "%" : ""}
            valueStyle={{ color: widget.config.color || "#3f8600" }}
          />
        );

      case "progress":
        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Title level={5}>{widget.title}</Title>
            <Progress
              percent={widget.data.percent}
              status={
                ["active", "success", "normal", "exception"].includes(widget.data.status as string)
                  ? (widget.data.status as "active" | "success" | "normal" | "exception")
                  : undefined
              }
              strokeColor={widget.config.color}
              showInfo={true}
            />
            {widget.data.description && (
              <Text type="secondary">{widget.data.description}</Text>
            )}
          </Space>
        );

      case "table":
        const columns: TableColumn[] = (widget.config.columns ?? []).map(
          (col: any) => ({
            title: col.title,
            dataIndex: col.dataIndex,
            key: col.key,
            render: typeof col.render === "function" ? col.render : undefined,
            sorter: col.sorter,
            width: col.width,
          }),
        );

        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Title level={5}>{widget.title}</Title>
            <Table
              dataSource={widget.data.rows}
              columns={columns}
              pagination={
                typeof widget.config.pagination === "object" ||
                  widget.config.pagination === false ||
                  widget.config.pagination === undefined
                  ? widget.config.pagination
                  : false
              }
              size="small"
              scroll={{ x: true }}
            />
          </Space>
        );

      case "list":
        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Title level={5}>{widget.title}</Title>
            <List
              dataSource={widget.data.items}
              renderItem={(item: any) => (
                <List.Item>
                  <List.Item.Meta
                    title={item.title}
                    description={item.description}
                  />
                  {item.extra && <div>{item.extra}</div>}
                </List.Item>
              )}
            />
          </Space>
        );

      case "text":
        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Title level={5}>{widget.title}</Title>
            <div dangerouslySetInnerHTML={{ __html: widget.data.html ?? "" }} />
          </Space>
        );

      case "chart":
        // For charts, we'll use a simple placeholder since we don't have chart library yet
        // In a real implementation, you'd use Chart.js, D3, or similar
        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Title level={5}>{widget.title}</Title>
            <div
              style={{
                height: widget.config.height || 300,
                background: "#f5f5f5",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px dashed #d9d9d9",
              }}
            >
              <Text type="secondary">
                Chart: {widget.config.chartType || "line"} -{" "}
                {JSON.stringify(widget.data)}
              </Text>
            </div>
          </Space>
        );

      default:
        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Title level={5}>{widget.title}</Title>
            <Text type="secondary">Unknown widget type: {widget.type}</Text>
          </Space>
        );
    }
  };

  return (
    <Card
      variant="borderless"
      style={{
        height: "100%",
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}
    >
      {renderContent()}
    </Card>
  );
};

export default WidgetRenderer;
